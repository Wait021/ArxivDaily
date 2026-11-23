# -*- coding: utf-8 -*-
"""入口：抓论文 → 按已有简介渲染 README.md 和每日 Issue 正文。

本文件不调模型：筛选笔记由 paper_agent.py 生成并缓存在 briefs.json，这里只读取。
每天 11:00 由 paper_agent.py 的本地计划任务驱动（GitHub Actions 已停用）。

用法：
  python main.py              # 抓取 + 渲染（可单独手动跑）
  TEST_MODE=1 python main.py  # 快速冒烟测试（少量抓取）
"""
import json
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import briefs as briefs_mod
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


STARS_BAR = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "⭐⭐⭐⭐", 5: "⭐⭐⭐⭐⭐"}
# 筛选笔记的三段：字段名 → 表格里显示的标签。"作者报告"和"判断"分开标，提醒读者前者是作者的声称
BRIEF_PARTS = (("what", "做法"), ("result", "作者报告"), ("verdict", "判断"))


def ai_cell(paper: dict, brief: dict | None, with_abstract: bool = True) -> str:
    """表格第三列：筛选笔记（做法 / 作者报告 / 判断）+ 相关度星级；没有笔记时回退到折叠的英文原摘要。

    brief 来自 briefs.json（按 arXiv 编号缓存）。
    with_abstract=False（日报 Issue 用）：有笔记时省略英文摘要。Issue 正文有 65536 字符上限，
    带着摘要只能放下前几个关键词，省掉后全部关键词都能进日报；完整版在 README 里。
    """
    abstract = esc(paper.get("abstract", ""))[:800]
    folded = f"<details><summary>📄 英文原摘要</summary><p>{abstract}</p></details>" if abstract else ""
    if not brief or not brief.get("what"):
        return folded or "（无摘要）"
    parts = [f"**{label}**：{brief[key].replace('|', '\\|')}" for key, label in BRIEF_PARTS if brief.get(key)]
    blocks = ["<br>".join(parts)]  # 三段之间单换行；星级、摘要各成一段，段间空一行
    stars = STARS_BAR.get(brief.get("stars", 0), "")
    if stars:
        blocks.append(f"**相关度 {stars}**")
    if folded and with_abstract:
        blocks.append(folded)
    return "<br><br>".join(blocks)


def paper_row(paper: dict, brief: dict | None = None, with_votes: bool = False,
              with_abstract: bool = True) -> str:
    votes = f" | **{paper['upvotes']}** 👍" if with_votes else ""
    comment = ""
    if paper.get("comment"):
        comment = f" <details><summary>💬</summary><p>{esc(paper['comment'])[:300]}</p></details>"
    pdf = f"https://arxiv.org/pdf/{paper['arxiv_id']}"
    return (
        f"| **[{esc(paper['title'])}]({paper['link']})** [📄]({pdf}){comment} "
        f"| {paper.get('date', '')}{votes} | {ai_cell(paper, brief, with_abstract)} |"
    )


def write_section(rm: list, issue: list, title: str, papers: list, briefs: dict,
                  issue_top: int, with_votes=False):
    rm.append(f"\n## {title}\n")
    if with_votes:
        rm.append("| **标题** | **日期** | **热度** | **筛选笔记** |")
        rm.append("| --- | --- | --- | --- |")
    else:
        rm.append("| **标题** | **日期** | **筛选笔记** |")
        rm.append("| --- | --- | --- |")
    issue.append(f"\n## {title}\n")
    issue.append("| **标题** | **日期** | **筛选笔记** |")
    issue.append("| --- | --- | --- |")
    for p in papers:
        rm.append(paper_row(p, briefs.get(p["arxiv_id"]), with_votes))
    for p in papers[:issue_top]:
        issue.append(paper_row(p, briefs.get(p["arxiv_id"]), with_abstract=False))


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


def build_tables(data: dict, briefs: dict, issue_top: int, trending_top: int) -> tuple[str, str]:
    """把 papers 数据渲染成 (README 正文, Issue 正文)。"""
    today = data["date"]
    rm = [f"# 📚 论文日报 · 翻译智能体 & Agent\n\n{config.README_INTRO}\n\nLast update: {today}\n\n"
          f"{preserve_deep_reading()}"]
    issue = []
    trending = data.get("trending", [])
    if trending:
        write_section(rm, issue, "🔥 本周热门 · Hugging Face Trending", trending, briefs,
                      trending_top, with_votes=True)
    keywords = data.get("keywords", {})
    for kw, papers in keywords.items():
        write_section(rm, issue, kw, papers, briefs, issue_top)
    head = f"📚 论文日报 {today} · 关键词：{('、'.join(keywords))}\n"
    return "\n".join(rm) + "\n", head + "\n".join(issue) + "\n"


def render(data: dict, briefs: dict, issue_top: int | None = None, trending_top: int | None = None):
    """按已有数据和简介写出 README.md、papers.json 和每日 Issue 的标题、正文。

    纯本地操作：不联网、不调模型。抓取之后、简介生成之后都调它来重写表格。
    """
    issue_top = config.ISSUE_RESULTS_PER_KEYWORD if issue_top is None else issue_top
    trending_top = config.TRENDING_TOP_N if trending_top is None else trending_top
    papers = briefs_mod.all_papers(data)
    covered = sum(1 for p in papers if p["arxiv_id"] in briefs)
    print(f"  表格共 {len(papers)} 篇论文，{covered} 篇有筛选笔记，{len(papers) - covered} 篇暂用英文摘要")
    readme, issue_body = build_tables(data, briefs, issue_top, trending_top)
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme)
    with open("papers.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.makedirs(ISSUE_DIR, exist_ok=True)
    with open(ISSUE_BODY_FILE, "w", encoding="utf-8") as f:
        f.write(issue_body)
    with open(ISSUE_TITLE_FILE, "w", encoding="utf-8") as f:
        f.write(f"📚 论文日报 - {data['date']}")


def collect() -> dict:
    """抓取热门榜和各关键词论文，返回 papers.json 的内容。"""
    days = 2 if TEST_MODE else config.TRENDING_DAYS
    top_n = 5 if TEST_MODE else config.TRENDING_TOP_N
    print(f"[1/3] 抓取 Hugging Face 最近 {days} 天热门论文 ...")
    trending = fetch_weekly_trending(days=days, top_n=top_n)
    for p in trending:
        p["pdf"] = f"https://arxiv.org/pdf/{p['arxiv_id']}"

    keywords = config.KEYWORDS[:2] if TEST_MODE else config.KEYWORDS
    per_kw = 5 if TEST_MODE else config.MAX_RESULTS_PER_KEYWORD
    keep = 5 if TEST_MODE else config.KEEP_PER_KEYWORD
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

    data = {"date": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"),
            "trending": trending, "keywords": {}}
    for kw in keywords:
        if kw not in kw_papers:
            continue
        papers = [p for p in kw_papers[kw] if p["arxiv_id"] not in seen][:keep]
        seen.update(p["arxiv_id"] for p in papers)
        for p in papers:
            p["pdf"] = f"https://arxiv.org/pdf/{p['arxiv_id']}"
        data["keywords"][kw] = papers

    if not data["keywords"] and not trending:
        raise SystemExit("所有数据源都失败了，不生成文件")
    return data


def main():
    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    print(f"=== 论文日报 {today} ===")
    data = collect()
    print("[3/3] 生成 README.md、papers.json 和每日 Issue ...")
    small = 5 if TEST_MODE else None  # 冒烟测试时每个分区只放少量论文
    render(data, briefs_mod.load_briefs(), issue_top=small, trending_top=small)
    print("完成：README.md 已更新，Issue 内容已生成")


if __name__ == "__main__":
    main()
