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
# 每次调用打包多少篇。筛选笔记是关掉模型思考生成的（见 paper_agent.write_briefs），
# 20 篇的输出只有约 3000 token，不会触及输出预算
BATCH_SIZE = 20
# 筛选笔记的写法版本。改写下面的 PROMPT 时把它加 1，旧写法的笔记会被视为不存在并自动重新生成
BRIEF_VERSION = 3

PROMPT = """你是我的论文筛选助手。我每天要从几百篇 arXiv 论文里挑出值得读全文的，现在只有标题和摘要。请为下面 {n} 篇论文各写一条筛选笔记。

我的研究方向：①翻译智能体（PPT/幻灯片、XML 等富结构文档的 LLM 翻译，文档级翻译及其评测）②生物智能体（药物发现、实验规划、自动化科研）③教学智能体（个性化辅导、智能教学）④LLM Agent 与工具调用。

每条笔记分三段，三段合计不超过 150 个字：
- what（做法）：这篇论文解决什么问题、怎么做，不超过 45 个字。用大白话，不堆术语；方法名、模型名、数据集名保留英文。
- result（作者报告）：摘要里的结果和关键数字，不超过 70 个字。这是作者的声称，不是已经证实的事实，不要替作者加"显著""大幅"这类评价。摘要声称了效果提升却没给任何数字，就写"摘要未给数字"；没有做效果声称的论文（发布数据集、介绍框架、立场文章等）写"无效果声称"。
- verdict（判断）：一句话，不超过 30 个字。只看摘要，说这篇最值得留意的地方：和我方向的关系，或者一眼能看出的局限（只有小规模评测、只有自动指标、只做一个语言对等）。和我方向无关的写"可跳过"加半句原因。

硬性要求：
- 只使用摘要里的信息，不要补充摘要没有的内容。
- stars 是相关度，按我的研究方向打 1 到 5 星：5 星是论文本身就在做我的方向；4 星是不做这些方向，但它的方法或工具能直接用上；3 星是有间接借鉴；2 星是只是同属一个大领域；1 星是基本无关。没有关系的论文要敢于打 1 星。
- 每句话都要有信息量，不写"具有重要意义""值得关注"这类空话。
- 严格按下面的格式输出，每篇一个 JSON 对象，各字段的值是一段不换行的文字，不要输出任何其他文字：

{{"id": "论文编号", "what": "做法", "result": "作者报告", "verdict": "判断", "stars": 3}}

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


def _repair(chunk: str) -> dict | None:
    """JSON 解析失败时的兜底：按键名用正则把字段取出来。

    模型偶尔在字段值里用了没转义的英文双引号，整条 JSON 就坏了。键的顺序是固定的，
    所以用"下一个键名"来切分字段的结尾。
    """
    id_match = re.search(r'"id"\s*:\s*"?(\d+)"?', chunk)
    if not id_match:
        return None

    def grab(key: str, next_key: str) -> str:
        m = re.search(rf'"{key}"\s*:\s*"(.*?)"(?=\s*,\s*"{next_key}"\s*:)', chunk, re.S)
        return m.group(1).strip() if m else ""

    what = grab("what", "result")
    if not what:
        return None
    stars = re.search(r'"stars"\s*:\s*"?([1-5])"?', chunk)
    return {"id": id_match.group(1), "what": what, "result": grab("result", "verdict"),
            "verdict": grab("verdict", "stars"), "stars": int(stars.group(1)) if stars else 1}


def _parse_batch(text: str, ids: list) -> dict:
    """从模型输出里取出每篇论文的 JSON 对象。

    不按行切：模型通常一行一个对象，但偶尔会换成带缩进的多行数组，或者在字段值里写没转义的
    英文双引号。这里用花括号把每个对象框出来逐个解析，解析失败的再按键名修一次。
    """
    out, wanted = {}, set(ids)
    for chunk in re.findall(r"\{[^{}]*\}", text, re.S):
        try:
            obj = json.loads(chunk)
        except json.JSONDecodeError:
            obj = _repair(chunk)
        if not isinstance(obj, dict):
            continue
        key = str(obj.get("id", "")).strip()
        parts = {f: " ".join(str(obj.get(f, "")).split()) for f in ("what", "result", "verdict")}
        try:
            stars = max(1, min(5, int(obj.get("stars", 1))))
        except (TypeError, ValueError):
            stars = 1
        # 模型偶尔会把三段合起来塞进 summary；这时当作"做法"收下，总比丢掉整条强
        if not parts["what"] and obj.get("summary"):
            parts["what"] = " ".join(str(obj["summary"]).split())
        if key in wanted and parts["what"]:
            out[key] = {"v": BRIEF_VERSION, **parts, "stars": stars}
    return out


def generate_briefs(papers: list, chat, existing: dict | None = None, on_progress=None) -> dict:
    """为 papers 里还没有笔记的论文批量生成。返回 {arxiv_id: {what, result, verdict, stars, v}}。

    chat(prompt, max_tokens=...) 由调用方传入（复用 paper_agent.chat，不重复实现重试）。
    第一轮按 BATCH_SIZE 分批；一轮下来仍有没拿到笔记的（模型输出格式跑偏、调用失败等），
    换成每批 10 篇再试一次。仍失败的论文不写入缓存，下次运行会自动补。
    on_progress(briefs) 在每批成功后回调，调用方用它及时落盘——
    避免最后一批崩掉、前面几批白花。
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

    def run(queue: list, size: int):
        for start in range(0, len(queue), size):
            batch = queue[start:start + size]
            lines = []
            for i, p in enumerate(batch, 1):
                lines.append(f"[{i}] 标题: {p['title']}\n    摘要: {p['abstract'][:2500]}")
            prompt = PROMPT.replace("{n}", str(len(batch))) + "\n".join(lines)
            ids = [str(i) for i in range(1, len(batch) + 1)]
            try:
                raw = chat(prompt, max_tokens=16000)
                got = _parse_batch(raw, ids)
            except Exception as e:
                print(f"    ✗ 这一批调用失败，稍后重试: {str(e)[:120]}", flush=True)
                continue
            for i, p in enumerate(batch, 1):
                if str(i) in got:
                    briefs[p["arxiv_id"]] = got[str(i)]
            if on_progress:
                on_progress(briefs)
            got_n = sum(1 for p in todo if p["arxiv_id"] in briefs)
            print(f"    笔记 {got_n}/{len(todo)}", flush=True)
            if len(got) < len(batch):
                # 把模型输出的开头打进日志，格式跑偏时才有线索可查
                print(f"    ⚠ 这批有 {len(batch) - len(got)} 篇没解析出来，模型输出开头：{raw[:150]!r}", flush=True)

    run(todo, BATCH_SIZE)
    leftover = [p for p in todo if p["arxiv_id"] not in briefs]
    if leftover:
        print(f"    {len(leftover)} 篇还没拿到笔记，换成每批 10 篇再试一次", flush=True)
        run(leftover, 10)
    return briefs


def all_papers(data: dict) -> list:
    """papers.json 里的全部论文（热门榜 + 各关键词），按 arXiv 编号去重。"""
    papers, seen = [], set()
    for p in list(data.get("trending", [])) + [p for ps in data.get("keywords", {}).values() for p in ps]:
        if p["arxiv_id"] not in seen:
            seen.add(p["arxiv_id"])
            papers.append(p)
    return papers
