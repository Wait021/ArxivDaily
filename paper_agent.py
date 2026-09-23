# -*- coding: utf-8 -*-
"""本地论文分析智能体。

流程：git pull 拿云端 papers.json → 选文 → 下载 PDF → pypdf 提取全文
     → GLM-5.3（1M 上下文）整篇直读生成中文深度解读 → 每日跨论文综述
     → 三路分发：summaries/ 存档推送 GitHub + 评论当天 Issue + README 索引

用法：
  python paper_agent.py              # 日常模式（8 篇）
  python paper_agent.py --test 1     # 测试模式：只分析 1 篇（省额度）
  python paper_agent.py --force      # 今天已分析过也强制重跑

密钥从 .env 读取（已被 .gitignore 排除，绝不推送 GitHub）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import config

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)
PDF_DIR = os.path.join(PROJ, "pdfs")
SUMMARY_DIR = os.path.join(PROJ, "summaries")
GH = r"C:\Program Files\GitHub CLI\gh.exe" if os.path.exists(r"C:\Program Files\GitHub CLI\gh.exe") else "gh"

# 每天分析的篇数：热门榜 3 + 关键词 5
TRENDING_N = 3
KEYWORD_N = 5
# 全文最多喂给模型的字符数（英文约 0.25 token/字符，留足 1M 上下文余量）
FULLTEXT_CHAR_LIMIT = 400_000

DEEP_PROMPT = """我的研究背景：{profile}

请通读下面这篇论文的全文（不是摘要，是完整正文），用中文输出一份深度解读：

## 🎯 研究动机与要解决的问题
## 🔧 方法（技术路线、关键设计、为什么这样设计）
## 📊 实验与结果（数据集、基线对比、主要数字）
## ⚠️ 局限与开放问题
## 💡 对我的研究的启发（结合我的研究背景，具体一点，比如能用到 PPT/XML 翻译智能体的哪些环节）

最后单独一行给出：**相关度：⭐⭐⭐⭐⭐（N 星，从我的研究背景出发打分）**

论文标题：{title}
论文全文：
{body}"""

REVIEW_PROMPT = """我的研究背景：{profile}

以下是今天 {n} 篇论文的深度解读。请写一篇 300 字左右的「今日趋势综述」：
这批论文共同指向什么趋势？哪些与我研究背景强相关值得优先精读？有没有可以直接借鉴到 PPT/XML 翻译智能体的想法？

{digests}"""


# ---------- 基础设施 ----------

def load_env() -> dict:
    env = {}
    with open(".env", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    for k in ("LLM_API_KEY",):
        if not env.get(k):
            sys.exit(f"✗ .env 缺少 {k}（.env 已 gitignore，只存本地）")
    env.setdefault("LLM_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4")
    env.setdefault("LLM_MODEL", "glm-5.3")
    return env


def chat(env: dict, prompt: str, max_tokens: int = 16000) -> str:
    """GLM 调用。GLM-5.3 是推理模型，思考也耗 token，预算必须给足；
    若 content 为空（思考吃光预算），自动加倍预算/关闭思考重试。"""

    def _post(body: dict):
        req = urllib.request.Request(
            env["LLM_BASE_URL"].rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + env["LLM_API_KEY"]})
        return json.loads(urllib.request.urlopen(req, timeout=600).read().decode("utf-8"))

    base = {
        "model": env["LLM_MODEL"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    last_err = None
    for attempt in range(3):
        try:
            r = _post(base)
            msg = r["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            usage = r.get("usage", {})
            if content:
                print(f"    [tokens] 输入{usage.get('prompt_tokens','?')} 输出{usage.get('completion_tokens','?')}")
                return content
            # content 为空：思考耗尽预算 → 加倍预算重试
            print(f"    ⚠ content 为空（completion={usage.get('completion_tokens')}），加倍预算重试 ...")
            retry = dict(base, max_tokens=min(max_tokens * (attempt + 2), 64000))
            if attempt >= 1:  # 第二次还空就尝试关闭思考（zhipu 扩展参数）
                retry["thinking"] = {"type": "disabled"}
            r = _post(retry)
            content = (r["choices"][0]["message"].get("content") or "").strip()
            if content:
                u2 = r.get("usage", {})
                print(f"    [tokens] 输入{u2.get('prompt_tokens','?')} 输出{u2.get('completion_tokens','?')}")
                return content
            last_err = "content 持续为空"
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")[:200]
            last_err = f"HTTP {e.code}: {body}"
            if e.code in (429, 500, 502, 503):
                time.sleep(20 * (attempt + 1))
                continue
            raise RuntimeError(last_err)
        except Exception as e:
            last_err = e
            time.sleep(10)
    raise RuntimeError(f"GLM 调用失败: {last_err}")


def sh(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", **kw)


# ---------- 数据获取 ----------

def pull_papers() -> dict:
    r = sh(["git", "pull", "--rebase", "origin", "main"])
    if r.returncode != 0:
        print(f"⚠ git pull 失败（{r.stderr.strip()[:100]}），用本地现有 papers.json 继续")
    with open("papers.json", encoding="utf-8") as f:
        return json.load(f)


def select_papers(data: dict, limit: int) -> list:
    """热门榜前 TRENDING_N 篇 + 各关键词轮询取，凑够 limit 篇，去重。"""
    picked, seen = [], set()

    def add(p):
        if p["arxiv_id"] not in seen:
            seen.add(p["arxiv_id"])
            picked.append(p)

    for p in data.get("trending", [])[:TRENDING_N]:
        add(p)
    kw_lists = [ps for ps in data.get("keywords", {}).values() if ps]
    i = 0
    while len(picked) < limit and kw_lists:
        for kl in kw_lists:
            if len(picked) >= limit:
                break
            if i < len(kl):
                add(kl[i])
        i += 1
        if i >= max(len(kl) for kl in kw_lists):
            break
    return picked[:limit]


def download_pdf(paper: dict) -> str:
    os.makedirs(PDF_DIR, exist_ok=True)
    path = os.path.join(PDF_DIR, paper["arxiv_id"].replace("/", "_") + ".pdf")
    if os.path.exists(path) and os.path.getsize(path) > 10_000:
        return path
    for url in (paper.get("pdf"), f"https://arxiv.org/pdf/{paper['arxiv_id']}"):
        if not url:
            continue
        try:
            data = net_get(url)  # 本地直连 arxiv 即可
            open(path, "wb").write(data)
            if len(data) > 10_000:
                return path
        except Exception as e:
            print(f"    下载失败（{e}），尝试下一个源")
    raise RuntimeError("PDF 下载失败")


def net_get(url: str) -> bytes:
    req = urllib.request.Request(url)  # 默认 UA，避免被 arXiv 拉黑
    return urllib.request.urlopen(req, timeout=120).read()


def extract_text(pdf_path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    text = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if len(text) < 2000:
        raise RuntimeError("PDF 文本提取过短（可能是扫描版）")
    return text[:FULLTEXT_CHAR_LIMIT]


# ---------- 分析与输出 ----------

def analyze(paper: dict, env: dict) -> str:
    pdf = download_pdf(paper)
    print(f"    全文 {os.path.getsize(pdf) // 1024}KB，提取中 ...")
    body = extract_text(pdf)
    print(f"    正文 {len(body)} 字符，GLM 全文直读中（1M 上下文）...")
    out = chat(env, DEEP_PROMPT.format(profile=config.RESEARCH_PROFILE, title=paper["title"], body=body))
    header = (f"### [{paper['title']}]({paper['link']})\n\n"
              f"`{paper['arxiv_id']}` · {paper.get('date', '')} · [PDF]({paper.get('pdf', '')})\n\n")
    return header + out + "\n"


def synthesize(digests: list, env: dict) -> str:
    joined = "\n\n---\n\n".join(
        f"#### {d['title']}\n{d['analysis'][:1500]}" for d in digests)
    print("  生成今日跨论文综述 ...")
    return chat(env, REVIEW_PROMPT.format(profile=config.RESEARCH_PROFILE, n=len(digests), digests=joined),
                max_tokens=8000)


# ---------- 三路分发 ----------

def publish(today: str, md: str, count: int):
    # ① summaries/ 存档
    os.makedirs(SUMMARY_DIR, exist_ok=True)
    path = os.path.join(SUMMARY_DIR, f"{today}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)

    # ② README 索引（标记区块内加一行）
    readme = open("README.md", encoding="utf-8").read()
    row = f"| {today} | {count} 篇 | [summaries/{today}.md](summaries/{today}.md) |"
    m = re.search(r"(<!-- DEEP_READING_START -->.*?\| 日期 \| 分析篇数 \| 链接 \|\n\| --- \| --- \| --- \|)", readme, re.S)
    if m:
        readme = readme.replace(m.group(1), m.group(1) + "\n" + row)
    elif "<!-- DEEP_READING_END -->" in readme:
        readme = readme.replace("<!-- DEEP_READING_END -->", f"\n{row}\n<!-- DEEP_READING_END -->")
    else:
        readme += (f"\n<!-- DEEP_READING_START -->\n## 📖 深度解读（本地 GLM 智能体生成）\n\n"
                   f"| 日期 | 分析篇数 | 链接 |\n| --- | --- | --- |\n{row}\n<!-- DEEP_READING_END -->\n")
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme)

    # 推送（summaries + README）
    sh(["git", "add", "summaries/", "README.md"])
    sh(["git", "commit", "-m", f"🤖 深度解读 {today}（{count} 篇）"])
    for _ in range(3):
        sh(["git", "pull", "--rebase", "origin", "main"])
        r = sh(["git", "push"])
        if r.returncode == 0:
            print("  ✓ 已推送到 GitHub")
            break
        time.sleep(5)

    # ③ 评论当天 Issue
    title = f"📚 论文日报 - {today}"
    r = sh([GH, "issue", "list", "--state", "open", "--json", "number,title", "--jq",
            f'.[] | select(.title == "{title}") | .number'])
    if r.stdout.strip():
        number = r.stdout.strip().splitlines()[0]
        r2 = sh([GH, "issue", "comment", number, "--body-file", path])
        print(f"  ✓ 已评论 Issue #{number}" if r2.returncode == 0 else f"  ⚠ Issue 评论失败: {r2.stderr[:100]}")
    else:
        print("  ⚠ 没找到当天的日报 Issue，跳过评论（summaries 已存档）")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=int, metavar="N", help="只分析前 N 篇（省额度）")
    parser.add_argument("--force", action="store_true", help="今天已分析过也重跑")
    args = parser.parse_args()

    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    out_path = os.path.join(SUMMARY_DIR, f"{today}.md")
    if os.path.exists(out_path) and not args.force:
        print(f"✓ {today} 已分析过（{out_path}），如需重跑加 --force")
        return

    env = load_env()
    print(f"=== 本地论文智能体 {today} | 模型 {env['LLM_MODEL']} ===")
    data = pull_papers()
    limit = args.test if args.test else (TRENDING_N + KEYWORD_N)
    papers = select_papers(data, limit)
    print(f"选定 {len(papers)} 篇：")
    for p in papers:
        print(f"  - [{p.get('date', '')}] {p['title'][:60]}")

    digests = []
    for i, p in enumerate(papers, 1):
        print(f"[{i}/{len(papers)}] 分析: {p['title'][:50]}")
        try:
            digests.append({"title": p["title"], "analysis": analyze(p, env)})
        except Exception as e:
            print(f"    ✗ 失败跳过: {e}")

    if not digests:
        sys.exit("✗ 全部失败，未生成文件")

    md = [f"# 📖 深度解读 · {today}\n",
          f"> 本地智能体（{env['LLM_MODEL']}，1M 上下文全文直读）分析了 {len(digests)} 篇论文\n"]
    if len(digests) > 1:
        try:
            md.append(f"## 🧭 今日趋势综述\n\n{synthesize(digests, env)}\n\n---\n")
        except Exception as e:
            print(f"⚠ 综述生成失败: {e}")
    for d in digests:
        md.append(d["analysis"] + "\n---\n")
    md.append(f"\n*分析时间：{datetime.now(ZoneInfo('Asia/Shanghai')):%Y-%m-%d %H:%M}*\n")

    publish(today, "\n".join(md), len(digests))
    print(f"✅ 完成：{out_path}")


if __name__ == "__main__":
    main()
