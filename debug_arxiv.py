# -*- coding: utf-8 -*-
"""逐个成分排查哪种查询写法触发 arXiv 406。"""
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://export.arxiv.org/api/query?"

QUERIES = [
    ("Q1 all:electron", "all:electron"),
    ("Q2 all带引号短语", 'all:"Translation Agent"'),
    ("Q3 ti:electron", "ti:electron"),
    ("Q4 ti带引号短语", 'ti:"Translation Agent"'),
    ("Q5 abs带引号短语", 'abs:"Translation Agent"'),
    ("Q6 ti OR abs 完整", 'ti:"Translation Agent" OR abs:"Translation Agent"'),
    ("Q7 ti AND abs", 'ti:"Translation" AND abs:"Translation"'),
]

def try_query(q, extra="&max_results=3"):
    url = BASE + "search_query=" + urllib.parse.quote(q, safe="") + extra
    try:
        r = urllib.request.urlopen(url, timeout=30)
        return f"OK {r.status} {len(r.read())}B"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:
        return f"ERR {type(e).__name__}: {e}"

print("== 只变查询词 ==")
for name, q in QUERIES:
    print(f"{name} -> {try_query(q)}")

print("== 固定完整查询，变附加参数 ==")
q = urllib.parse.quote('ti:"Translation Agent" OR abs:"Translation Agent"', safe="")
for extra_name, extra in [
    ("无附加", "&max_results=3"),
    ("加sortBy", "&max_results=3&sortBy=lastUpdatedDate"),
    ("加sortOrder", "&max_results=3&sortBy=lastUpdatedDate&sortOrder=descending"),
]:
    url = BASE + "search_query=" + q + extra
    try:
        r = urllib.request.urlopen(url, timeout=30)
        print(f"{extra_name} -> OK {r.status} {len(r.read())}B")
    except urllib.error.HTTPError as e:
        print(f"{extra_name} -> HTTP {e.code}")

print("== urlencode 整体编码对比（当前代码的用法） ==")
params = {"search_query": 'ti:"Translation Agent" OR abs:"Translation Agent"',
          "max_results": "3", "sortBy": "lastUpdatedDate", "sortOrder": "descending"}
url = BASE + urllib.parse.urlencode(params)
try:
    r = urllib.request.urlopen(url, timeout=30)
    print(f"urlencode -> OK {r.status} {len(r.read())}B")
except urllib.error.HTTPError as e:
    print(f"urlencode -> HTTP {e.code}")
    for k, v in e.headers.items():
        print(f"  {k}: {v}")
