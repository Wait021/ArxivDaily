# -*- coding: utf-8 -*-
"""本地交互式深度阅读工具：让 GLM-5.3 精读单篇论文，并支持追问。

用法（在你的终端里）：
  python read_paper.py 2609.24967            # 传 arXiv 编号
  python read_paper.py https://arxiv.org/abs/2609.24967   # 或链接

优先下载 PDF 全文（pypdf 提取），失败则退回 arXiv HTML 版。
密钥从 .env 读取（已 gitignore，只存本地）。
输出：动机 → 方法 → 实验 → 局限 → 对你研究的启发，之后进入追问模式（空行退出）。
"""
import os
import re
import sys

import config
from paper_agent import DEEP_PROMPT, chat, load_env, net_get, ungrounded_numbers

# 精读用的提示词与每日自动精读是同一份（paper_agent.DEEP_PROMPT），保证两种方式读出来的笔记格式一致

ASK_PROMPT = """基于下面这篇论文，回答我的问题。用中文，直接给答案，可引用论文细节。

论文内容：
{body}

我的问题：{question}"""


def extract_id(arg: str) -> str:
    m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", arg)
    if not m:
        raise SystemExit(f"无法从参数里解析 arXiv 编号: {arg}")
    return m.group(1)


def get_fulltext(arxiv_id: str):
    """返回 (标题, 正文)。优先 PDF，失败用 arXiv HTML。"""
    import xml.etree.ElementTree as ET
    meta = net_get(f"https://export.arxiv.org/api/query?id_list={arxiv_id}").decode("utf-8")
    tm = re.search(r"<title>(.*?)</title>", meta[meta.find("<entry>"):], re.S)
    title = " ".join(tm.group(1).split()) if tm else arxiv_id

    # ① PDF（最完整）
    try:
        pdf_path = os.path.join("pdfs", arxiv_id.replace("/", "_") + ".pdf")
        if not (os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 10_000):
            os.makedirs("pdfs", exist_ok=True)
            open(pdf_path, "wb").write(net_get(f"https://arxiv.org/pdf/{arxiv_id}"))
        from pypdf import PdfReader
        text = " ".join((p.extract_text() or "") for p in PdfReader(pdf_path).pages)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 2000:
            return title, text
    except Exception as e:
        print(f"（PDF 读取失败: {e}，改用 HTML 版）")

    # ② arXiv HTML 兜底
    import html as html_lib
    for url in (f"https://arxiv.org/html/{arxiv_id}", f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"):
        try:
            raw = net_get(url).decode("utf-8", errors="ignore")
            raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", html_lib.unescape(raw))
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 2000:
                return title, text
        except Exception:
            continue
    raise SystemExit("拿不到论文全文（PDF 和 HTML 都失败）")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    env = load_env()
    arxiv_id = extract_id(sys.argv[1])
    print(f"获取论文 {arxiv_id} 全文 ...")
    title, body = get_fulltext(arxiv_id)
    print(f"《{title}》 {len(body)} 字符\n大模型精读中（需要 1-3 分钟）...\n")
    print("=" * 60)
    notes = chat(env, DEEP_PROMPT.format(profile=config.RESEARCH_PROFILE, title=title, body=body))
    print(notes)
    unchecked = ungrounded_numbers(notes, body)
    if unchecked:
        print(f"\n⚠️ 数字核对：这些数字在论文抽取文本里完全找不到，引用前请对照原文：{'、'.join(unchecked)}")
    print("=" * 60)

    while True:
        try:
            q = input("\n💬 追问（直接回车退出）> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            break
        print(chat(env, ASK_PROMPT.format(body=body, question=q)))


if __name__ == "__main__":
    main()
