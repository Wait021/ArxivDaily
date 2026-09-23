# -*- coding: utf-8 -*-
"""在 GitHub Actions 环境里测试 arXiv API 各种请求组合，找出不被 406 的那种。"""
import urllib.error
import urllib.parse
import urllib.request

KW = "Translation Agent"
ENC = urllib.parse.quote(f'ti:"{KW}" OR abs:"{KW}"', safe="%/:=&?~#+!$,;'@()*[]")

variants = [
    # (名字, URL, 自定义UA)  None=用 Python 默认 UA
    ("V1 手工quote http 默认UA", f"http://export.arxiv.org/api/query?search_query={ENC}&max_results=3&sortBy=lastUpdatedDate", None),
    ("V2 手工quote https 默认UA", f"https://export.arxiv.org/api/query?search_query={ENC}&max_results=3&sortBy=lastUpdatedDate", None),
    ("V3 urlencode http 默认UA", "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": f'ti:"{KW}" OR abs:"{KW}"', "max_results": "3", "sortBy": "lastUpdatedDate"}), None),
    ("V4 urlencode https 默认UA", "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": f'ti:"{KW}" OR abs:"{KW}"', "max_results": "3", "sortBy": "lastUpdatedDate"}), None),
    ("V5 urlencode https 诚实UA", "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": f'ti:"{KW}" OR abs:"{KW}"', "max_results": "3", "sortBy": "lastUpdatedDate"}),
        "ArxivDaily-Agent/1.0 (https://github.com/Wait021/ArxivDaily; mailto:errant-kimono48@icloud.com)"),
    ("V6 urlencode https 浏览器UA", "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": f'ti:"{KW}" OR abs:"{KW}"', "max_results": "3", "sortBy": "lastUpdatedDate"}),
        "Mozilla/5.0 (X11; Linux x86_64) ArxivDaily-Agent/1.0"),
    ("V7 https Accept头", "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": f'ti:"{KW}" OR abs:"{KW}"', "max_results": "3", "sortBy": "lastUpdatedDate"}),
        "__ACCEPT__"),
]

for name, url, ua in variants:
    headers = {}
    if ua == "__ACCEPT__":
        headers = {"Accept": "application/atom+xml"}
    elif ua:
        headers = {"User-Agent": ua}
    try:
        req = urllib.request.Request(url, headers=headers)
        r = urllib.request.urlopen(req, timeout=30)
        body = r.read()
        print(f"{name} -> OK {r.status} {len(body)}B")
    except urllib.error.HTTPError as e:
        print(f"{name} -> HTTP {e.code}")
    except Exception as e:
        print(f"{name} -> ERR {type(e).__name__}: {e}")
