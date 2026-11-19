"""Google Play 数据源：基于 goopdl 的匿名令牌，无需自己的 Google 账号。"""
import os
import threading

from goopdl import Client, Config

_client = None
_client_lock = threading.Lock()


def get_client() -> Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                proxy = (
                    os.environ.get("HTTPS_PROXY")
                    or os.environ.get("https_proxy")
                    or os.environ.get("ALL_PROXY")
                    or os.environ.get("all_proxy")
                )
                options = {}
                if proxy:
                    options["proxy"] = proxy
                _client = Client(Config(**options))
    return _client


def search(keyword: str, limit: int = 20) -> list[dict]:
    """搜索 Google Play；只返回轻量字段，版本/大小在下载时由 goopdl 获取。"""
    results = get_client().search(keyword, limit=limit)
    return [
        {
            "source": "gplay",
            "id": item["package"],
            "name": item.get("title") or item["package"],
            "pkg": item["package"],
            "developer": item.get("creator") or "",
            "version": "",
            "size": 0,
            "icon": "",
            "category": "Google Play",
            "rating": "",
            "url": "",
        }
        for item in results
    ]
