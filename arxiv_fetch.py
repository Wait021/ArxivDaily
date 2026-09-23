# -*- coding: utf-8 -*-
"""从 arXiv 官方 API 按关键词抓论文（标题/摘要/链接/更新日期/作者评论）。"""
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# 经验教训（2026-09-23 排查）：arXiv API 会拉黑自定义 bot UA（持续 406），
# 用 Python 默认 UA（Python-urllib/x.x，与海量正常脚本一致）最稳定——
# 参考 yanghlll/ArxivDaily-Haolin 多月稳定运行的用法。
# 同时必须保持请求间隔 ≥3 秒 + 失败退避重试，避免触发限流。

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
ARXIV_API = "https://export.arxiv.org/api/query"


def _fetch(keyword: str, max_results: int) -> str:
    # 单个词：要求同时出现在标题和摘要；多个词：作为短语出现在标题或摘要
    link = "AND" if len(keyword.split()) == 1 else "OR"
    query = f'ti:"{keyword}" {link} abs:"{keyword}"'
    params = {
        "search_query": query,
        "max_results": str(max_results),
        "sortBy": "lastUpdatedDate",
        "sortOrder": "descending",
    }
    url = ARXIV_API + "?" + urllib.parse.urlencode(params)
    # 不带任何自定义头，让 urllib 用默认 UA 直连
    return urllib.request.urlopen(url, timeout=60).read().decode("utf-8")


def fetch_papers(keyword: str, max_results: int, retries: int = 5):
    """返回论文列表 [{arxiv_id,title,abstract,link,date,comment}]，全部失败返回 None。

    arXiv API 偶发 406/空结果（限流/后端抖动）。实测限流恢复需要 1-2 分钟，
    短间隔重试只会反复撞墙，所以退避节奏拉长：15s → 45s → 90s → 120s → 120s
    """
    backoffs = [15, 45, 90, 120, 120]
    for i in range(retries):
        try:
            root = ET.fromstring(_fetch(keyword, max_results))
            papers = []
            for entry in root.findall(f"{ATOM}entry"):
                def txt(tag, ns=ATOM, default=""):
                    node = entry.find(f"{ns}{tag}")
                    return node.text.strip() if node is not None and node.text else default

                link = txt("id")
                papers.append({
                    "arxiv_id": link.split("/abs/")[-1],
                    "title": " ".join(txt("title").split()),
                    "abstract": " ".join(txt("summary").split()),
                    "link": link,
                    "date": txt("updated")[:10],
                    "comment": " ".join(txt("comment", ARXIV_NS).split()),
                })
            if papers:
                return papers
            # arXiv API 偶发返回空列表，也走重试
        except Exception as e:
            print(f"    arXiv 请求失败：{e}")
        time.sleep(backoffs[min(i, len(backoffs) - 1)])
    return None
