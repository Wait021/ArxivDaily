# -*- coding: utf-8 -*-
"""本地深度阅读工具：让大模型精读单篇论文，并支持追问。

用法（在你的终端里）：
  set LLM_API_KEY=你的key           # Windows CMD（Git Bash 用 export）
  set LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4   # 可选
  set LLM_MODEL=glm-4.6                                     # 可选
  python read_paper.py 2609.24967            # 传 arXiv 编号
  python read_paper.py https://arxiv.org/abs/2609.24967   # 或链接

输出：动机 → 方法 → 实验结果 → 局限 → 对你研究的启发，之后进入追问模式（输空行退出）。
"""
import re
import sys

import config
import net
from summarizer import _chat, fetch_fulltext, llm_enabled

DEEP_PROMPT = """我的研究背景：{profile}

请精读下面这篇论文，用中文输出一份深度解读：
## 🎯 研究动机与要解决的问题
## 🔧 方法（技术路线、关键设计、为什么这样设计）
## 📊 实验与结果（数据集、基线、主要结论）
## ⚠️ 局限与开放问题
## 💡 对我的研究的启发（结合我的研究背景，具体一点）

论文标题：{title}

论文内容：
{body}"""

ASK_PROMPT = """基于下面这篇论文和已有的解读，回答我的问题。用中文，直接给答案。

论文标题：{title}

论文内容：
{body}

我的问题：{question}"""


def extract_id(arg: str) -> str:
    m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", arg)
    if not m:
        raise SystemExit(f"无法从参数里解析 arXiv 编号: {arg}")
    return m.group(1)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    if not llm_enabled():
        raise SystemExit("请先设置环境变量 LLM_API_KEY（可选 LLM_BASE_URL / LLM_MODEL）")

    arxiv_id = extract_id(sys.argv[1])
    print(f"下载论文 {arxiv_id} 全文 ...")
    # 先拿元数据（标题）
    import re as _re
    meta = net.get(f"https://export.arxiv.org/api/query?id_list={arxiv_id}", timeout=60, direct=True).decode("utf-8")
    title_m = _re.search(r"<title>(.*?)</title>", meta[meta.find("<entry>"):], re.S)
    title = " ".join(title_m.group(1).split()) if title_m else arxiv_id

    body = fetch_fulltext(arxiv_id)
    if not body:
        raise SystemExit("拿不到全文（该论文可能没有 HTML 版），试试直接把摘要贴给模型。")

    import os
    cfg = {
        "key": os.environ["LLM_API_KEY"].strip(),
        "base_url": os.environ.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/"),
        "model": os.environ.get("LLM_MODEL", "glm-4.6"),
    }
    print("大模型精读中，需要 1-2 分钟 ...\n")
    print("=" * 60)
    print(_chat(cfg, DEEP_PROMPT.format(profile=config.RESEARCH_PROFILE, title=title, body=body)))
    print("=" * 60)

    # 追问模式
    while True:
        try:
            q = input("\n💬 追问（直接回车退出）> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            break
        print(_chat(cfg, ASK_PROMPT.format(title=title, body=body, question=q)))


if __name__ == "__main__":
    main()
