"""路径、上游接口与常量配置。"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DOWNLOAD_DIR = BASE_DIR / "downloads"
MANIFEST_PATH = DOWNLOAD_DIR / "manifest.json"

SEARCH_URL = "https://yybadaccess.3g.qq.com/v2/dc_pcyyb_official"
APK_CDN = "https://dd.myapp.com/16891/apk/{md5}.apk"
PAGE_SIZE = 20

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)

SEARCH_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Origin": "https://sj.qq.com",
    "Referer": "https://sj.qq.com/",
    "Content-Type": "application/json",
}

DOWNLOAD_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Referer": "https://sj.qq.com/",
}

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
