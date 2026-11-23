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
# 每次调用打包多少篇。20 篇时模型的思考会把输出预算占满导致截断（2026-11-23 实测 20 篇只出来 15 篇），
# 降到 15 篇并配合 generate_briefs 里的输出预算
BATCH_SIZE = 15
# 筛选笔记的写法版本。改写下面的 PROMPT 时把它加 1，旧写法的笔记会被视为不存在并自动重新生成
BRIEF_VERSION = 2

PROMPT = """你是我的论文筛选助手。我每天要从几百篇 arXiv 论文里挑出值得读全文的，现在只有标题和摘要。请为下面 {n} 篇论文各写一条筛选笔记。

我的研究方向：①翻译智能体（PPT/幻灯片、XML 等富结构文档的 LLM 翻译，文档级机器翻译评测）②生物智能体（药物发现、实验规划、自动化科研）③教学智能体（个性化辅导、智能教学）④LLM Agent 与工具调用。

每条笔记 80 到 130 个字，按这个顺序写：
1. 这篇论文解决什么问题、怎么做。用大白话，不堆术语；方法名、模型名、数据集名保留英文。
2. 作者声称的结果。摘要里有数字就带上数字。一律用"作者称""作者报告"引出，不要写成已经证实的事实。如果摘要声称了效果提升却没给任何数字，在后面写"摘要未给数字"；没有做效果声称的论文（比如发布数据集、介绍框架）不写这句。
3. 一句判断：只看摘要，这篇最值得留意的地方。比如只有小规模评测、只有自动指标、是立场或综述文章、和我的方向关系不大但某个设计可以借鉴。没有值得特别指出的，这一句省略。

硬性要求：
- 只使用摘要里的信息，不要补充摘要没有的内容，也不要替作者下"效果好""显著提升"这类结论。
- 相关度按我的研究方向打 1 到 5 星：5 星是论文本身就在做我的方向（翻译智能体、富结构文档翻译、文档级翻译及其评测、生物智能体、教学智能体）；4 星是不做这些方向，但它的方法或工具能直接用上；3 星是有间接借鉴；2 星是只是同属一个大领域；1 星是基本无关。没有关系的论文要敢于打 1 星。
- 每句话都要有信息量，不写"具有重要意义""值得关注"这类空话。
- 严格按下面的格式输出，每篇一个 JSON 对象，不要输出任何其他文字：

{{"id": "论文编号", "summary": "筛选笔记", "stars": 星数}}

论文列表：
"""


def load_briefs() -> dict:
    """读取缓存，只保留当前写法版本的条目（PROMPT 改版后，旧条目会被重新生成）。"""
    if not os.path.exists(BRIEFS_FILE):
        return {}
    with open(BRIEFS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if v.get("v") == BRIEF_VERSION}


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
            out[key] = {"v": BRIEF_VERSION, "summary": summary, "stars": stars}
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
            lines.append(f"[{i}] 标题: {p['title']}\n    摘要: {p['abstract'][:2500]}")
        prompt = PROMPT.replace("{n}", str(len(batch))) + "\n".join(lines)
        done = min(start + len(batch), len(todo))
        try:
            got = _parse_batch(chat(prompt, max_tokens=24000), [str(i) for i in range(1, len(batch) + 1)])
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
