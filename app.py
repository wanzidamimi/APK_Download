"""应用宝 APK 下载器 Web 服务。

启动：python -m uvicorn app:app --host 127.0.0.1 --port 8899
"""
from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import downloader
import gplay
import yyb
from config import DOWNLOAD_DIR, STATIC_DIR

app = FastAPI(title="应用宝 APK 下载器")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/sources")
def api_sources():
    return {"sources": [
        {"id": "yyb", "name": "应用宝", "desc": "国内安卓应用，APK 直链"},
        {"id": "gplay", "name": "Google Play", "desc": "海外应用，goopdl 匿名下载"},
    ]}


@app.get("/api/search")
async def api_search(q: str = "", page: int = 1, source: str = "yyb"):
    try:
        if source == "gplay":
            apps = await run_in_threadpool(gplay.search, q, 20)
            return {
                "apps": apps, "page": page, "has_more": False,
                "keyword": q, "source": source,
            }
        data = await yyb.search(q, page)
        data["source"] = source
        return data
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": f"搜索失败：{exc}"}, status_code=502
        )


@app.post("/api/download")
async def api_download(payload: dict = Body(...)):
    return downloader.start_download(payload)


@app.get("/api/tasks")
def api_tasks():
    return {"tasks": downloader.get_tasks()}


@app.get("/api/files")
def api_files():
    return {"files": downloader.list_files(), "dir": str(DOWNLOAD_DIR)}


@app.delete("/api/files/{file_id}")
def api_delete(file_id: str):
    return {"ok": downloader.delete_file(file_id)}


@app.post("/api/cancel/{task_id}")
def api_cancel(task_id: str):
    return {"ok": downloader.cancel_download(task_id)}


@app.post("/api/open-folder")
def api_open_folder(payload: dict | None = Body(default=None)):
    file_id = (payload or {}).get("file_id")
    path = None
    if file_id:
        entry = next(
            (e for e in downloader.list_files() if e.get("id") == file_id), None
        )
        if not entry:
            return JSONResponse({"ok": False, "error": "文件不存在"}, status_code=404)
        path = entry["path"]
    try:
        opened = downloader.open_folder(path, select=bool(path))
        return {"ok": True, "path": opened}
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": f"打开目录失败：{exc}"}, status_code=500
        )


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
