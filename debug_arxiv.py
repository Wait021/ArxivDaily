# -*- coding: utf-8 -*-
"""调试：看 406 响应头，判断是哪一层在拦截。"""
import urllib.error
import urllib.request

url = "https://export.arxiv.org/api/query?search_query=all:electron&max_results=1"
try:
    r = urllib.request.urlopen(url, timeout=30)
    print("OK", r.status)
except urllib.error.HTTPError as e:
    print("HTTP", e.code)
    for k, v in e.headers.items():
        print(f"  {k}: {v}")
    print("  body:", e.read()[:300])
