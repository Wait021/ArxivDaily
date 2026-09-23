# -*- coding: utf-8 -*-
"""从 arXiv 官方 API 按关键词抓论文（标题/摘要/链接/更新日期/作者评论）。"""
import time
import urllib.parse
import xml.etree.ElementTree as ET

import net

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
ARXIV_API = "https://export.arxiv.org/api/query"
# arXiv API 要求自动化客户端用可表明身份的 UA（带联系方式），
# 从数据中心 IP（如 GitHub Actions）用伪装浏览器的 UA 会被拒（HTTP 406）
USER_AGENTS = [
    "ArxivDaily-Agent/1.0 (https://github.com/Wait021/ArxivDaily; mailto:errant-kimono48@icloud.com)",
    "Mozilla/5.0 (compatible; ArxivDailyBot/1.0; +https://github.com/Wait021/ArxivDaily)",
]


def _fetch(keyword: str, max_results: int, ua: str) -> str:
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
    return net.get(url, timeout=60, direct=True, headers={"User-Agent": ua}).decode("utf-8")


def fetch_papers(keyword: str, max_results: int, retries: int = 7):
    """返回论文列表 [{arxiv_id,title,abstract,link,date,comment}]，全部失败返回 None。

    arXiv API 会间歇性返回 406（限流/后端抽风），同一样查询重试往往就通了，
    所以用指数退避：5s → 10s → 20s → 30s → 45s → 60s → 60s
    """
    backoffs = [5, 10, 20, 30, 45, 60, 60]
    for i in range(retries):
        try:
            root = ET.fromstring(_fetch(keyword, max_results, USER_AGENTS[i % len(USER_AGENTS)]))
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
