# -*- coding: utf-8 -*-
"""从 arXiv 官方 API 按关键词抓论文（标题/摘要/链接/更新日期/作者评论）。"""
import time
import urllib.parse
import xml.etree.ElementTree as ET

import net

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
ARXIV_API = "http://export.arxiv.org/api/query"


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
    # arXiv 直连更稳（代理可能破坏证书链）
    url = ARXIV_API + "?" + urllib.parse.urlencode(params)
    return net.get(url, timeout=60, direct=True).decode("utf-8")


def fetch_papers(keyword: str, max_results: int, retries: int = 5):
    """返回论文列表 [{arxiv_id,title,abstract,link,date,comment}]，全部失败返回 None。"""
    for _ in range(retries):
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
            # arXiv API 偶发返回空列表，睡 5 秒重试
        except Exception as e:
            print(f"    arXiv 请求失败：{e}")
        time.sleep(5)
    return None
