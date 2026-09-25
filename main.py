# -*- coding: utf-8 -*-
"""入口：抓论文 → AI 全文总结 → 生成 README.md 和每日 Issue。

用法：
  python main.py          # 完整运行（GitHub Actions 每天自动跑，也可本地手动跑）
  TEST_MODE=1 python main.py  # 快速冒烟测试（少量抓取，不调 LLM）
"""
import json
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import summarizer
from arxiv_fetch import fetch_papers
from trending import fetch_weekly_trending

# 无控制台/重定向环境下防止 GBK 编码崩溃（打印 ⚠ 等字符）
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TEST_MODE = os.environ.get("TEST_MODE") == "1"

ISSUE_DIR = ".github"
ISSUE_BODY_FILE = os.path.join(ISSUE_DIR, "daily_issue.md")
ISSUE_TITLE_FILE = os.path.join(ISSUE_DIR, "issue_title.txt")


def esc(text: str) -> str:
    """转义 Markdown 表格单元格里的竖线和换行。"""
    return text.replace("|", "\\|").replace("\n", "<br>").strip()


def ai_cell(paper: dict) -> str:
    """表格第三列：优先 AI 总结，其次折叠的原始摘要。"""
    if paper.get("ai_summary"):
        return "<br>".join(paper["ai_summary"].splitlines())
    abstract = esc(paper.get("abstract", ""))[:800]
    return f"<details><summary>📄 摘要</summary><p>{abstract}</p></details>" if abstract else ""


def paper_row(paper: dict, with_votes: bool = False) -> str:
    votes = f" | **{paper['upvotes']}** 👍" if with_votes else ""
    comment = ""
    if paper.get("comment"):
        comment = f" <details><summary>💬</summary><p>{esc(paper['comment'])[:300]}</p></details>"
    pdf = f"https://arxiv.org/pdf/{paper['arxiv_id']}"
    return (
        f"| **[{esc(paper['title'])}]({paper['link']})** [📄]({pdf}){comment} "
        f"| {paper.get('date', '')}{votes} | {ai_cell(paper)} |"
    )


def write_section(rm: list, issue: list, title: str, papers: list, issue_top: int, with_votes=False):
    rm.append(f"\n## {title}\n")
    if with_votes:
        rm.append("| **标题** | **日期** | **热度** | **🤖 AI 总结** |")
        rm.append("| --- | --- | --- | --- |")
    else:
        rm.append("| **标题** | **日期** | **🤖 AI 总结** |")
        rm.append("| --- | --- | --- |")
    issue.append(f"\n## {title}\n")
    issue.append("| **标题** | **日期** | **🤖 AI 总结** |")
    issue.append("| --- | --- | --- |")
    for p in papers:
        rm.append(paper_row(p, with_votes))
    for p in papers[:issue_top]:
        issue.append(paper_row(p, False))


def preserve_deep_reading() -> str:
    """从旧 README 里保留「深度解读」区块（本地智能体写入的内容，不能被每日重建覆盖）。"""
    default = ("<!-- DEEP_READING_START -->\n## 📖 深度解读（本地 GLM 智能体生成）\n\n"
               "_每天上午由本地智能体深度分析后更新，云端爬虫保留下表_\n\n"
               "| 日期 | 分析篇数 | 链接 |\n| --- | --- | --- |\n"
               "<!-- DEEP_READING_END -->")
    try:
        old = open("README.md", encoding="utf-8").read()
        m = re.search(r"<!-- DEEP_READING_START -->.*?<!-- DEEP_READING_END -->", old, re.S)
        return m.group(0) if m else default
    except OSError:
        return default


def main():
    beijing = ZoneInfo("Asia/Shanghai")
    today = datetime.now(beijing).strftime("%Y-%m-%d")
    print(f"=== 论文日报 {today} ===")

    rm = [f"# 📚 论文日报 · 翻译智能体 & Agent\n\n{config.README_INTRO}\n\nLast update: {today}\n\n{preserve_deep_reading()}"]
    issue = []

    # ---- 本周热门（Hugging Face Trending）----
    days = 2 if TEST_MODE else config.TRENDING_DAYS
    top_n = 5 if TEST_MODE else config.TRENDING_TOP_N
    print(f"[1/3] 抓取 Hugging Face 最近 {days} 天热门论文 ...")
    trending = fetch_weekly_trending(days=days, top_n=top_n)
    n_sum = 2 if TEST_MODE else config.SUMMARIZE_TRENDING
    for i, p in enumerate(trending[:n_sum]):
        print(f"  AI 总结 {i + 1}/{n_sum}: {p['title'][:50]}")
        p["ai_summary"] = summarizer.summarize_paper(p) if not TEST_MODE else ""
    if trending:
        write_section(rm, issue, f"🔥 本周热门 · Hugging Face Trending", trending, top_n, with_votes=True)

    # ---- 关键词论文 ----
    keywords = config.KEYWORDS[:2] if TEST_MODE else config.KEYWORDS
    per_kw = 5 if TEST_MODE else config.MAX_RESULTS_PER_KEYWORD
    keep = 5 if TEST_MODE else config.KEEP_PER_KEYWORD
    n_sum = 1 if TEST_MODE else config.SUMMARIZE_PER_KEYWORD
    seen = {p["arxiv_id"] for p in trending}  # 跨关键词去重

    print(f"[2/3] 抓取 arXiv 关键词论文（{len(keywords)} 个关键词）...")
    kw_papers, failed = {}, []
    for kw in keywords:
        print(f"  关键词: {kw}")
        papers = fetch_papers(kw, per_kw)
        if papers is None:
            print("    抓取失败，稍后二次补抓")
            failed.append(kw)
        else:
            kw_papers[kw] = papers
        time.sleep(4)  # arXiv 官方要求的礼貌间隔（≥3 秒）

    if failed and not TEST_MODE:
        print(f"  等 90 秒后二次补抓 {len(failed)} 个失败关键词 ...")
        time.sleep(90)
        for kw in failed[:]:
            print(f"  补抓: {kw}")
            papers = fetch_papers(kw, per_kw)
            if papers is not None:
                kw_papers[kw] = papers
                failed.remove(kw)
            time.sleep(4)

    ok_keywords = 0
    export = {"date": today, "trending": [], "keywords": {}}
    if trending:
        for p in trending:
            p["pdf"] = f"https://arxiv.org/pdf/{p['arxiv_id']}"
        export["trending"] = trending
    for kw in keywords:
        if kw not in kw_papers:
            continue
        papers = [p for p in kw_papers[kw] if p["arxiv_id"] not in seen][:keep]
        seen.update(p["arxiv_id"] for p in papers)
        for p in papers:
            p["pdf"] = f"https://arxiv.org/pdf/{p['arxiv_id']}"
        for i, p in enumerate(papers[:n_sum]):
            print(f"  AI 总结 {i + 1}/{n_sum}: {p['title'][:50]}")
            p["ai_summary"] = summarizer.summarize_paper(p) if not TEST_MODE else ""
        write_section(rm, issue, kw, papers, config.ISSUE_RESULTS_PER_KEYWORD if not TEST_MODE else keep)
        export["keywords"][kw] = papers
        ok_keywords += 1

    if ok_keywords == 0 and not trending:
        raise SystemExit("所有数据源都失败了，不生成文件")

    # ---- 写文件 ----
    print("[3/3] 生成 README.md、papers.json 和每日 Issue ...")
    with open("README.md", "w", encoding="utf-8") as f:
        f.write("\n".join(rm) + "\n")
    with open("papers.json", "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=1)
    os.makedirs(ISSUE_DIR, exist_ok=True)
    with open(ISSUE_BODY_FILE, "w", encoding="utf-8") as f:
        f.write(f"📚 论文日报 {today} · 关键词：{('、'.join(keywords))}\n" + "\n".join(issue) + "\n")
    with open(ISSUE_TITLE_FILE, "w", encoding="utf-8") as f:
        f.write(f"📚 论文日报 - {today}")
    print("完成：README.md 已更新，Issue 内容已生成")


if __name__ == "__main__":
    main()
