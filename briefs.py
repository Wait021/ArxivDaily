# -*- coding: utf-8 -*-
"""给每篇论文生成中文简介 + 相关度星级（表格「总结」列用）。

与深度解读的区别：深度解读（paper_agent.py）是读 PDF 全文、每篇单独调用、只做 8 篇；
简介只读摘要，**多篇打包进一次调用**，所以能覆盖表格里的全部论文。

简介按 arXiv 编号缓存在 briefs.json 里。同一篇论文会在列表里连续出现多天，
已生成过的直接复用，每天只需要为新出现的论文付费。
"""
import json
import os
import re

BRIEFS_FILE = "briefs.json"
BATCH_SIZE = 20  # 每次调用打包多少篇（实测 20 篇约 100 秒、输出 8K token）

PROMPT = """你是论文筛选助手。下面有 {n} 篇 arXiv 论文的标题和摘要。请为每一篇写中文简介。

我的研究方向：①翻译智能体（PPT/幻灯片、XML 等富结构文档的 LLM 翻译，文档级机器翻译评测）②生物智能体（药物发现、实验规划、自动化科研）③教学智能体（个性化辅导、智能教学）④LLM Agent 与工具调用。

要求：
- 每篇 2 到 3 句中文，80 到 120 字。用中文写，论文专有名词、模型名、数据集名保留英文。
- 先说这篇论文解决什么问题、怎么做，再说主要结果。不要写空话。
- 相关度：按我的研究方向打 1 到 5 星。5 星是直接做翻译智能体或文档级翻译，1 星是基本无关。没有关系的论文要敢于打 1 星。
- 严格按下面的格式输出，每篇一个 JSON 对象，不要输出任何其他文字。

{{"id": "论文编号", "summary": "中文简介", "stars": 星数}}

论文列表：
"""


def load_briefs() -> dict:
    if os.path.exists(BRIEFS_FILE):
        with open(BRIEFS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_briefs(briefs: dict):
    with open(BRIEFS_FILE, "w", encoding="utf-8") as f:
        json.dump(briefs, f, ensure_ascii=False, indent=1)


def _parse_batch(text: str, ids: list) -> dict:
    """从模型输出里解析 JSON 行。容忍模型加的 Markdown 代码围栏。"""
    out = {}
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    wanted = set(ids)
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = str(obj.get("id", "")).strip()
        summary = str(obj.get("summary", "")).strip()
        try:
            stars = max(1, min(5, int(obj.get("stars", 1))))
        except (TypeError, ValueError):
            stars = 1
        if key in wanted and summary:
            out[key] = {"summary": summary, "stars": stars}
    return out


def generate_briefs(papers: list, chat, existing: dict | None = None, on_progress=None) -> dict:
    """为 papers 里还没有简介的论文批量生成。返回 {arxiv_id: {summary, stars}}。

    chat(prompt, max_tokens=...) 由调用方传入（复用 paper_agent.chat，不重复实现重试）。
    单批失败只丢那一批，不影响其他批次；失败的论文不写入缓存，下次运行会自动补。
    on_progress(briefs) 在每批成功后回调，调用方用它及时落盘——
    避免 14 批里最后一批崩掉、前面 13 批的钱白花。
    """
    briefs = dict(existing or {})
    seen, todo = set(), []
    for p in papers:
        if p["arxiv_id"] in seen:
            continue
        seen.add(p["arxiv_id"])
        if p["arxiv_id"] not in briefs and p.get("abstract"):
            todo.append(p)
    if not todo:
        return briefs
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        lines = []
        for i, p in enumerate(batch, 1):
            lines.append(f"[{i}] 标题: {p['title']}\n    摘要: {p['abstract'][:900]}")
        prompt = PROMPT.replace("{n}", str(len(batch))) + "\n".join(lines)
        done = min(start + len(batch), len(todo))
        try:
            got = _parse_batch(chat(prompt, max_tokens=16000), [str(i) for i in range(1, len(batch) + 1)])
        except Exception as e:
            # 不写入缓存：这批论文下次运行会重新生成
            print(f"    ✗ 这一批简介失败（{done - len(batch) + 1}-{done}），下次补: {str(e)[:120]}", flush=True)
            continue
        for i, p in enumerate(batch, 1):
            if str(i) in got:
                briefs[p["arxiv_id"]] = got[str(i)]
        missing = len(batch) - len(got)
        note = f"（{missing} 篇未解析出，下次补）" if missing else ""
        print(f"    简介 {done}/{len(todo)}{note}", flush=True)
        if on_progress:
            on_progress(briefs)
    return briefs


def all_papers(data: dict) -> list:
    """papers.json 里的全部论文（热门榜 + 各关键词），按 arXiv 编号去重。"""
    papers, seen = [], set()
    for p in list(data.get("trending", [])) + [p for ps in data.get("keywords", {}).values() for p in ps]:
        if p["arxiv_id"] not in seen:
            seen.add(p["arxiv_id"])
            papers.append(p)
    return papers
