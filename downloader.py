"""后台下载任务、进度跟踪与已下载清单持久化。"""
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from config import DOWNLOAD_DIR, DOWNLOAD_HEADERS, MANIFEST_PATH

_tasks = {}
_manifest = []
_lock = threading.RLock()


def _safe_name(value: str, limit: int = 48) -> str:
    value = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", value or "").strip(" .")
    return value[:limit] or "app"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _save_manifest() -> None:
    MANIFEST_PATH.write_text(
        json.dumps(_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_manifest() -> None:
    """读取清单，并把目录中存在但清单缺失的 APK 补录进去。"""
    global _manifest
    if MANIFEST_PATH.exists():
        try:
            _manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            _manifest = []
    known = {entry.get("path") for entry in _manifest}
    changed = False
    for entry in _manifest:
        if not entry.get("source"):
            entry["source"] = "yyb"
            changed = True
    for path in sorted(DOWNLOAD_DIR.glob("*.apk")):
        if str(path) in known:
            continue
        stat = path.stat()
        _manifest.insert(0, {
            "id": uuid.uuid4().hex[:12],
            "source": "yyb",
            "name": path.stem,
            "pkg": "",
            "version": "",
            "md5": "",
            "size": stat.st_size,
            "filename": path.name,
            "path": str(path),
            "downloaded_at": _now(),
        })
        changed = True
    if changed or not MANIFEST_PATH.exists():
        _save_manifest()


load_manifest()


def list_files() -> list:
    with _lock:
        return sorted(_manifest, key=lambda e: e.get("downloaded_at", ""), reverse=True)


def get_tasks() -> list:
    with _lock:
        return list(_tasks.values())


def _task_key(task: dict) -> str:
    if task.get("source") == "gplay":
        return "gplay:" + (task.get("pkg") or "")
    return "yyb:" + (task.get("md5") or "").upper()


def _entry_key(entry: dict) -> str:
    if entry.get("source") == "gplay":
        return "gplay:" + (entry.get("pkg") or "")
    return "yyb:" + (entry.get("md5") or "").upper()


def start_download(app: dict) -> dict:
    source = app.get("source") or "yyb"
    if source == "gplay":
        pkg = (app.get("pkg") or "").strip()
        if not pkg or "." not in pkg:
            return {"ok": False, "error": "无效的包名"}
        key, md5 = "gplay:" + pkg, ""
    else:
        md5 = (app.get("md5") or "").strip()
        if not re.match(r"^[0-9a-fA-F]{32}$", md5):
            return {"ok": False, "error": "无效的 APK 标识"}
        key = "yyb:" + md5.upper()

    with _lock:
        for task in _tasks.values():
            if _task_key(task) == key and task["status"] in ("downloading", "done"):
                return {"ok": True, "task_id": task["id"], "reused": True}
        for entry in _manifest:
            if _entry_key(entry) == key:
                return {"ok": True, "task_id": entry["id"], "reused": True, "done": True}

        task_id = uuid.uuid4().hex[:12]
        task = {
            "id": task_id,
            "source": source,
            "name": app.get("name") or "app",
            "pkg": app.get("pkg") or "",
            "version": app.get("version") or "",
            "md5": md5,
            "url": app.get("url") or "",
            "size": int(app.get("size") or 0),
            "downloaded": 0,
            "speed": 0,
            "status": "downloading",
            "error": "",
            "started_at": _now(),
            "cancel": False,
        }
        _tasks[task_id] = task

    target = _run_gplay_download if source == "gplay" else _run_download
    threading.Thread(target=target, args=(task,), daemon=True).start()
    return {"ok": True, "task_id": task_id, "reused": False}


def _detail_apk_url(pkg: str) -> str | None:
    """MD5 直链失效时，从移动端详情页解析真实 apkUrl。"""
    if not pkg:
        return None
    detail = "https://a.app.qq.com/o/simple.jsp?pkgname=" + quote(pkg)
    try:
        resp = httpx.get(
            detail, headers=DOWNLOAD_HEADERS, follow_redirects=True, timeout=20
        )
        match = re.search(r'"apkUrl":"([^"]+)"', resp.text)
        if match:
            return match.group(1).replace("\\/", "/").replace("\\u0026", "&")
    except Exception:
        pass
    return None


def _stream_to(task: dict, url: str, temp_path: Path) -> int:
    """流式下载单个地址，返回写入字节数；网页响应直接判为失败。"""
    last_time = time.monotonic()
    last_bytes = 0
    written = 0
    with httpx.stream(
        "GET",
        url,
        headers=DOWNLOAD_HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, read=30.0),
    ) as response:
        response.raise_for_status()
        ctype = response.headers.get("content-type", "").lower()
        if not any(k in ctype for k in ("android.package-archive", "apk", "octet-stream")):
            raise ValueError("地址返回的不是 APK（可能是网页）")
        total = int(response.headers.get("content-length") or 0)
        with _lock:
            if total:
                task["size"] = total
        with temp_path.open("wb") as handle:
            for chunk in response.iter_bytes(chunk_size=256 * 1024):
                if task["cancel"]:
                    raise InterruptedError("用户取消下载")
                if not chunk:
                    continue
                handle.write(chunk)
                written += len(chunk)
                now = time.monotonic()
                with _lock:
                    task["downloaded"] = written
                    elapsed = now - last_time
                    if elapsed >= 0.5:
                        task["speed"] = int((written - last_bytes) / elapsed)
                        last_time, last_bytes = now, written
    return written


def _looks_like_apk(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"PK"
    except OSError:
        return False


def _run_gplay_download(task: dict) -> None:
    """用 goopdl 下载 Google Play 的 base APK，并纳入统一的进度/清单流程。"""
    from gplay import get_client

    temp_dir = DOWNLOAD_DIR / (".gplay-" + task["id"])
    temp_dir.mkdir(parents=True, exist_ok=True)
    last_time = time.monotonic()
    last_bytes = 0

    def on_progress(label: str, done: int, total: int | None) -> None:
        nonlocal last_time, last_bytes
        now = time.monotonic()
        with _lock:
            task["downloaded"] = done
            if total:
                task["size"] = total
            elapsed = now - last_time
            if elapsed >= 0.5:
                task["speed"] = int((done - last_bytes) / elapsed)
                last_time, last_bytes = now, done

    try:
        result = get_client().download(
            task["pkg"], temp_dir, on_progress=on_progress,
            splits=False, extras=False,
        )
        source_file = Path(result.path)
        if not source_file.exists():
            candidates = [Path(p) for p in (result.files or ()) if Path(p).exists()]
            if not candidates:
                raise RuntimeError("Google Play 未返回 APK 文件")
            source_file = candidates[0]

        version = result.version_string or task["version"]
        final_path = DOWNLOAD_DIR / "{}_{}_{}.apk".format(
            _safe_name(task["name"]),
            _safe_name(version, 24),
            _safe_name(task["pkg"], 40),
        )
        shutil.move(str(source_file), str(final_path))
        actual = final_path.stat().st_size

        with _lock:
            task["status"] = "done"
            task["version"] = version
            task["size"] = actual
            task["downloaded"] = actual
            task["speed"] = 0
            task["error"] = ""
            task["path"] = str(final_path)
            task["filename"] = final_path.name
            _manifest.insert(0, {
                "id": task["id"],
                "source": "gplay",
                "name": task["name"],
                "pkg": task["pkg"],
                "version": version,
                "md5": "",
                "size": actual,
                "filename": final_path.name,
                "path": str(final_path),
                "downloaded_at": _now(),
            })
            _save_manifest()
    except Exception as exc:
        with _lock:
            task["status"] = "canceled" if task["cancel"] else "error"
            task["error"] = str(exc)
            task["speed"] = 0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _run_download(task: dict) -> None:
    filename = "{}_{}_{}.apk".format(
        _safe_name(task["name"]),
        _safe_name(task["version"], 24),
        _safe_name(task["pkg"], 40),
    )
    final_path = DOWNLOAD_DIR / filename
    temp_path = DOWNLOAD_DIR / (filename + ".part")

    try:
        used_fallback = False
        while True:
            temp_path.unlink(missing_ok=True)
            url = _detail_apk_url(task["pkg"]) if used_fallback else task["url"]
            if not url:
                raise RuntimeError("无法获取 APK 下载地址")
            try:
                written = _stream_to(task, url, temp_path)
                if written < 1024 or not _looks_like_apk(temp_path):
                    raise ValueError("下载内容不是有效 APK")
                break
            except InterruptedError:
                raise
            except Exception as exc:
                if used_fallback or not task["pkg"]:
                    raise
                used_fallback = True
                with _lock:
                    task["downloaded"] = 0
                    task["error"] = "直链失效，改从详情页解析：" + str(exc)

        actual = temp_path.stat().st_size
        temp_path.replace(final_path)
        with _lock:
            task["size"] = actual
            task["downloaded"] = actual
            task["status"] = "done"
            task["speed"] = 0
            task["error"] = ""
            task["path"] = str(final_path)
            task["filename"] = filename
            _manifest.insert(0, {
                "id": task["id"],
                "source": "yyb",
                "name": task["name"],
                "pkg": task["pkg"],
                "version": task["version"],
                "md5": task["md5"],
                "size": actual,
                "filename": filename,
                "path": str(final_path),
                "downloaded_at": _now(),
            })
            _save_manifest()
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        with _lock:
            task["status"] = "canceled" if task["cancel"] else "error"
            task["error"] = str(exc)
            task["speed"] = 0


def cancel_download(task_id: str) -> bool:
    with _lock:
        task = _tasks.get(task_id)
        if not task or task["status"] != "downloading":
            return False
        task["cancel"] = True
        return True


def delete_file(file_id: str) -> bool:
    with _lock:
        entry = next((e for e in _manifest if e.get("id") == file_id), None)
        if not entry:
            return False
        try:
            Path(entry["path"]).unlink(missing_ok=True)
        except OSError:
            pass
        _manifest.remove(entry)
        _save_manifest()
        return True


def open_folder(path: str | None = None, select: bool = False) -> str:
    target = Path(path) if path else DOWNLOAD_DIR
    target = target.resolve()
    if target.is_file():
        select, target = True, target.parent
    if sys.platform == "win32":
        args = ["explorer", "/select,", str(target)] if select else ["explorer", str(target)]
    elif sys.platform == "darwin":
        args = ["open", "-R", str(target)] if select else ["open", str(target)]
    else:
        args = ["xdg-open", str(target)]
    subprocess.Popen(args)
    return str(target)
