# -*- coding: utf-8 -*-
"""Hugging Face 每日热门论文（https://huggingface.co/papers）→ 聚合成本周热门榜。"""
import json
from datetime import date, timedelta

import net

HF_API = "https://huggingface.co/api/daily_papers"


def fetch_weekly_trending(days: int = 7, top_n: int = 12):
    """抓最近 N 天的每日热门，按论文去重后取点赞数最高的前 top_n 篇。"""
    best = {}  # arxiv_id -> paper（同一篇论文保留点赞数最高的一天快照）
    for i in range(days):
        d = (date.today() - timedelta(days=i)).isoformat()
        url = f"{HF_API}?date={d}"
        try:
            data = json.loads(net.get(url, timeout=60).decode("utf-8"))
        except Exception as e:
            print(f"    获取 {d} 的热门榜失败：{e}，跳过")
            continue
        for item in data:
            p = item["paper"]
            pid = p["id"]
            if pid not in best or p.get("upvotes", 0) > best[pid].get("upvotes", 0):
                best[pid] = {
                    "arxiv_id": pid,
                    "title": " ".join(p.get("title", "").split()),
                    "abstract": " ".join(p.get("summary", "").split()),
                    "link": f"https://arxiv.org/abs/{pid}",
                    "date": (p.get("publishedAt") or "")[:10],
                    "upvotes": p.get("upvotes", 0),
                    "github": p.get("githubRepo") or "",
                }
    ranked = sorted(best.values(), key=lambda x: -x["upvotes"])
    return ranked[:top_n]
