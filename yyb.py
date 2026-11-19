"""应用宝搜索：只保留真正的安卓 APK，过滤电脑版 exe。"""
import re
import uuid

import httpx

from config import APK_CDN, PAGE_SIZE, SEARCH_HEADERS, SEARCH_URL

MD5_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def _build_body(keyword: str, page: int, size: int) -> dict:
    return {
        "head": {
            "cmd": "dc_pcyyb_official",
            "authInfo": {"businessId": "AuthName"},
            "deviceInfo": {"platformType": 1, "platform": 3},
            "userInfo": {"guid": str(uuid.uuid4())},
            "expSceneIds": "",
            "hostAppInfo": {"scene": "search_result"},
        },
        "body": {
            "bid": "yybhome",
            "offset": max(0, page - 1) * size,
            "size": size,
            "preview": False,
            "listS": {
                "region": {"repStr": ["CN"]},
                "keyword": {"repStr": [keyword]},
            },
            "layout": "yybn_search_result_list",
        },
    }


def _apk_url(md5: str) -> str:
    # CDN 路径大小写敏感，必须保留接口返回的原始大写 MD5
    return APK_CDN.format(md5=md5)


async def search(keyword: str, page: int = 1) -> dict:
    keyword = (keyword or "").strip()
    if not keyword:
        return {"apps": [], "page": page, "has_more": False, "keyword": keyword}

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.post(
            SEARCH_URL,
            json=_build_body(keyword, page, PAGE_SIZE),
            headers=SEARCH_HEADERS,
        )
        resp.raise_for_status()
        payload = resp.json()

    apps = []
    for component in ((payload.get("data") or {}).get("components") or []):
        for item in ((component.get("data") or {}).get("itemData") or []):
            md5 = (item.get("md_5") or "").strip()
            # 无有效 md5 的结果是电脑版 exe，直接丢弃
            if not MD5_RE.match(md5):
                continue
            apps.append({
                "name": item.get("name") or "",
                "pkg": item.get("pkg_name") or "",
                "version": item.get("version_name") or "",
                "size": int(item.get("apk_size") or 0),
                "md5": md5,
                "icon": item.get("icon") or "",
                "developer": item.get("developer") or "",
                "category": item.get("cate_name_new") or "",
                "rating": item.get("average_rating") or "",
                "url": _apk_url(md5),
            })

    return {
        "apps": apps,
        "page": page,
        "has_more": len(apps) >= PAGE_SIZE,
        "keyword": keyword,
    }
