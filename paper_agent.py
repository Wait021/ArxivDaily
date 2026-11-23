# -*- coding: utf-8 -*-
"""本地论文分析智能体。

流程：git pull 拿云端 papers.json → 选文 → 下载 PDF → pypdf 提取全文
     → GLM-5.3（1M 上下文）整篇直读生成中文深度解读 → 每日阅读指引
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

# 定时任务/重定向环境下 Python 输出默认走 GBK，打印 ⚠✓ 等字符会直接崩溃，强制 UTF-8
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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

# 深度解读的写法借鉴了几份开源读论文技能的共识：先讲清再评价；逐条核查"主张—证据—结论"；
# 严格区分论文写的和读者推断的；数字要带出处；只谈真实相关的价值；给可执行的建议而不是分数。
DEEP_PROMPT = """你是一位资深的 LLM 与智能体方向研究者，审稿经验丰富。请替我批判性精读下面这篇论文的全文，写成一份笔记，让没读过这篇论文的人读完能判断三件事：它说了什么，靠不靠谱，对我有没有用。

我的研究背景：{profile}
读者是我：熟悉 LLM 和 Agent 的基础知识，但不了解这篇论文所在的子方向。

## 动笔前先想清楚（这部分不要输出）
1. 先读摘要、引言末尾的贡献列表和结论，列出作者的核心主张。
2. 判断论文类型：方法、系统/数据集/基准、理论、实证、综述/观点，可以有主有次。不同类型的论文，合格的证据不一样。方法论文看基线和消融；基准论文看数据构成、指标是否合理、对比是否公平、有没有泄漏风险；理论论文看假设和证明；综述看覆盖范围和选材方式。
3. 再读方法和实验，把每条主张对应到具体证据。论文没有主张过的东西，不要替它补。

## 输出格式（严格遵守，小节标题照抄）
#### 概览
先写"论文类型：…"。再用两三句话写清楚：这篇论文用什么办法解决什么问题；最过硬的一条证据是什么；你对它可靠程度的总体判断。

#### 问题与思路
- 要解决的问题，以及它为什么值得解决。
- 之前的做法差在哪。只写论文自己对比的那几类，不要泛泛地说"传统方法"。
- 核心直觉：这个想法为什么能成立。用一个具体例子走一遍：输入是什么，经过哪几步，输出是什么。

#### 证据核查
用一张表覆盖摘要和引言里的全部核心主张：
| 作者的主张 | 论文给出的证据 | 支撑程度 | 最大缺口 |
"论文给出的证据"一栏写明出处（第几节、表几、图几）、关键数字、对比对象和实验条件。
"支撑程度"只用三档：站得住、部分成立、证据不足。
核查时重点看这几件事：基线是不是当前最强的做法、有没有认真调过；有没有消融实验；有没有多次运行的方差或显著性信息；评测是谁做的、有没有报告评分者之间的一致性；数据有没有泄漏风险、和训练分布是不是太接近；结论有没有超出实验实际覆盖的范围。哪一项论文没报告，就写"未报告"，不要写成"没做"。

#### 最脆弱的一环
哪一个假设、实验设计或对比一旦不成立，主要结论就会跟着动摇。说明原因，再写一句：要检验它，最小的做法是什么。

#### 边界
分两组写：**作者承认的局限**、**我的质疑**。每条质疑写出来源位置、它对结论的影响、你有多大把握。只写会改变结论或使用方式的问题，不列通用缺点，也不为了显得严格而挑刺。没有实质质疑就直说。

#### 对我的价值
只写和我研究方向真实相关的内容。论文本身的发现，和你由此对我项目做的推断，分开写，后者标明"我的推断"。和我的方向关系不大时直说，最多给一条可迁移的思路，不要硬找联系。

#### 结论
三选一：值得精读、值得浏览、暂不必读。用一两句话说明理由。
最后一行单独写相关度，格式固定为：相关度：⭐⭐⭐⭐⭐（按我的研究方向打 1 到 5 星，几星写几颗，不加别的文字，不要加粗）

## 写作要求
- 严格区分四种信息：论文明确写的、领域里已有的共识、你根据证据做出的推断、你的猜测。论文写的用"论文报告""作者称"；你的判断用"我判断""我推断"；没把握就写"不确定"。不要把推断写成事实。
- 不夸大。小规模或单一设置下的结果不要写成"证明"，写"在该设置下显示"。
- 数字必须逐字来自原文，并带上对比对象、数据集和条件。照抄原文的小数位，不要自己取整或省略小数；确实要取近似，就在数字前面加"约"。相对提升和绝对提升分清楚；你自己换算出来的数字要在后面用括号标明（换算）。原文抽取错乱、看不清的表格或公式不要猜，写"原文抽取不清，未能核对"。
- 每句话都要有信息量。不写"值得注意的是""至关重要""具有重要意义"这类空话，不用"不是……而是……"的句式，不堆砌术语。
- 不打小数分数。
- 篇幅控制在 1500 到 3000 个汉字，表格里的内容不计。宁短勿滥。

论文标题：{title}

论文全文：
{body}"""

REVIEW_PROMPT = """我的研究背景：{profile}

下面是我今天精读的 {n} 篇论文的笔记。请写一份 350 字以内的阅读指引：
1. 按对我的价值从高到低排序，每篇用一句话说明它排在这个位置的原因。
2. 如果这几篇之间确实有共同点或相互印证，指出来；没有关联就直说，不要硬凑趋势。
3. 最后写一条：如果今天只读一篇，读哪篇，为什么。如果有可以直接用到 PPT/XML 翻译智能体上的做法，指出来，并标明它是论文的结论还是你的推断。
只依据下面的笔记，不要补充笔记里没有的信息。区分论文的结论和你的推断。

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


def chat(env: dict, prompt: str, max_tokens: int = 32000, thinking: bool = True) -> str:
    """GLM 调用，返回完整的回答正文。

    输出预算不够时接口有两种表现，都不能直接采用：正文被截断并返回 finish_reason == "length"
    （2026-11-23 实测），或正文为空。返回里只有正文，看不到模型在正文之外花了多少 token；
    usage 里的 reasoning_tokens 字段实测约等于输出总数减一、开关思考都一样，不能当思考量用。
    处理顺序：预算翻倍重试，上限 64000；还不够就关闭思考再试（thinking 参数已实测可用，
    代价是分析会浅一些，但总比半截强）。

    thinking=False 直接关闭模型思考，用在不需要深度推理的任务上。2026-11-24 实测同一批 15 篇摘要的
    筛选笔记：开着思考 16 分钟、6 万多输出 token，关掉后 34 秒、2100 个 token，质量没有下降。
    """

    def _post(body: dict):
        req = urllib.request.Request(
            env["LLM_BASE_URL"].rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + env["LLM_API_KEY"]})
        return json.loads(urllib.request.urlopen(req, timeout=600).read().decode("utf-8"))

    body = {
        "model": env["LLM_MODEL"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    if not thinking:
        body["thinking"] = {"type": "disabled"}
    last_err = None
    for attempt in range(4):
        try:
            r = _post(body)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")[:200]
            last_err = f"HTTP {e.code}: {err_body}"
            if e.code in (429, 500, 502, 503):
                time.sleep(20 * (attempt + 1))
                continue
            raise RuntimeError(last_err)
        except Exception as e:
            last_err = e
            time.sleep(10)
            continue
        choice = r["choices"][0]
        content = (choice["message"].get("content") or "").strip()
        usage = r.get("usage", {})
        if content and choice.get("finish_reason") != "length":
            print(f"    [tokens] 输入{usage.get('prompt_tokens', '?')} 输出{usage.get('completion_tokens', '?')}")
            return content
        last_err = f"{'正文被截断' if content else '正文为空'}（预算 {body['max_tokens']}）"
        print(f"    ⚠ {last_err}，重试 ...")
        if body["max_tokens"] < 64000:
            body = dict(body, max_tokens=min(body["max_tokens"] * 2, 64000))
        elif body.get("thinking") is None:
            body = dict(body, max_tokens=max_tokens, thinking={"type": "disabled"})  # 最后手段
        else:
            break
    raise RuntimeError(f"GLM 调用失败: {last_err}")


def sh(cmd: list, timeout: float = None, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, **kw)


# ---------- 数据获取 ----------

def pull_papers() -> dict:
    r = sh(["git", "pull", "--rebase", "origin", "main"])
    if r.returncode != 0:
        print(f"⚠ git pull 失败（{r.stderr.strip()[:100]}），用本地现有 papers.json 继续")
    with open("papers.json", encoding="utf-8") as f:
        return json.load(f)


def heal_if_needed(data: dict) -> dict:
    """papers.json 缺失、关键词为空、或不是今天的数据时，本地重新抓取。

    云端 arXiv 被限流时关键词会缺失；git pull 失败时会残留旧的本地文件——
    两种情况都必须补抓，否则会拿过期论文做分析。
    """
    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    if data.get("keywords") and data.get("date") == today:
        return data
    if not data.get("keywords"):
        print("⚠ 云端关键词抓取失败（arXiv 对数据中心限流），本地补抓中 ...")
    else:
        print(f"⚠ papers.json 是旧数据（{data.get('date')} ≠ {today}），本地重抓 ...")
    try:
        r = sh([sys.executable, "main.py"], timeout=1200)  # 20 分钟硬上限，防 DNS/代理僵死
    except subprocess.TimeoutExpired:
        print("⚠ 本地补抓超时（20 分钟，疑似网络僵死），用现有数据继续")
        return data
    if r.returncode != 0:
        print(f"⚠ 本地补抓失败: {r.stderr[-200:] if r.stderr else r.stdout[-200:]}")
        return data
    with open("papers.json", encoding="utf-8") as f:
        healed = json.load(f)
    if healed.get("date") == today:
        print(f"✓ 本地补抓完成：{len(healed.get('keywords', {}))} 组关键词")
        return healed
    print("⚠ 补抓后日期仍不符，凑合用最新数据")
    return healed


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

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")


def ungrounded_numbers(notes: str, source: str) -> list:
    """找出笔记里出现、但论文抽取文本里完全找不到的数字，用来发现模型编造的数字。

    这是个很粗的核对：只能发现原文里根本不存在的数字，发现不了抄错一位、小数点错位、
    把百分比读成分数这类错误。为了少误报，匹配前去掉原文里的空白和千分位逗号（PDF 抽取
    会把数字拆行、把相邻的表格单元粘在一起），并且按不带边界的子串匹配。
    年份和 13 以内的整数不查；标了"换算"或前面带"约"的是模型自己算的或取的近似，也不查。
    """
    flat = re.sub(r"[\s,]", "", source)
    notes = re.sub(r"\d+(?:[.,]\d+)*%?\s*[（(][^（）()]*换算[^（）()]*[）)]", "", notes)
    notes = re.sub(r"[~≈约]\s*\d+(?:[.,]\d+)*%?", "", notes)
    seen, missing = set(), []
    for tok in _NUM_RE.findall(notes):
        bare = tok.replace(",", "")
        if bare in seen:
            continue
        seen.add(bare)
        try:
            value = float(bare)
        except ValueError:  # 形如 0.128.0 的版本号或 IP，不是普通数字
            continue
        if value < 13 and value.is_integer() or 1990 <= value <= 2099:
            continue
        if bare in flat:
            continue
        missing.append(tok)
    return missing


def analyze(paper: dict, env: dict) -> str:
    pdf = download_pdf(paper)
    print(f"    全文 {os.path.getsize(pdf) // 1024}KB，提取中 ...")
    body = extract_text(pdf)
    print(f"    正文 {len(body)} 字符，GLM 全文直读中（1M 上下文）...")
    out = chat(env, DEEP_PROMPT.format(profile=config.RESEARCH_PROFILE, title=paper["title"], body=body))
    unchecked = ungrounded_numbers(out, body)
    if len(unchecked) >= 3:
        # 不拦下整篇：把对不上原文的数字列出来，让读者引用前自己核对
        out = out.rstrip() + (
            "\n\n> ⚠️ 数字核对：下面这些数字在论文的抽取文本里完全找不到，引用前请对照 PDF 核实："
            + "、".join(unchecked))
        print(f"    ⚠ 有 {len(unchecked)} 个数字在原文里没找到，已在笔记末尾标注")
    header = (f"### [{paper['title']}]({paper['link']})\n\n"
              f"`{paper['arxiv_id']}` · {paper.get('date', '')} · [PDF]({paper.get('pdf', '')})\n\n")
    return header + out + "\n"


def synthesize(digests: list, env: dict) -> str:
    # 只把每篇的「概览」和「结论」交给模型：判断和理由都在这两节里，比截取开头一段更完整
    parts = []
    for d in digests:
        text = d["analysis"]
        start = text.find("#### 概览")  # 跳过笔记开头的标题行
        if start >= 0:
            text = text[start:]
        overview = text.split("#### 问题与思路")[0].strip()[:1200]
        conclusion = text.split("#### 结论")[-1].strip() if "#### 结论" in text else ""
        parts.append(f"**{d['title']}**\n{overview}\n…\n#### 结论\n{conclusion}")
    print("  生成今日阅读指引 ...")
    return chat(env, REVIEW_PROMPT.format(profile=config.RESEARCH_PROFILE, n=len(digests),
                                          digests="\n\n---\n\n".join(parts)),
                max_tokens=16000)


# ---------- 三路分发 ----------

def prepare_issue_body(path: str = ".github/daily_issue.md") -> str:
    """Issue 正文超 GraphQL 65536 字符上限时截断（关键词多后必超），加链接尾注。

    返回实际可用的 body 文件路径（未超长则用原文件）。
    """
    LIMIT = 64000  # GitHub 上限是 65536 个字符（实测按字符数计，不是字节）
    body = open(path, encoding="utf-8").read()
    if len(body) <= LIMIT:
        return path
    cut = body[:LIMIT]
    nl = cut.rfind("\n")  # 在行边界截断，避免破坏表格行
    if nl > LIMIT * 0.8:
        cut = cut[:nl]
    cut += ("\n\n---\n\n> 📋 论文表格过长已截断。完整列表见 [README](https://github.com/Wait021/ArxivDaily)，"
            "当日深度解读见本 Issue 下方评论。\n")
    out = ".github/daily_issue_body.md"
    open(out, "w", encoding="utf-8").write(cut)
    return out


def find_issue(title: str) -> str | None:
    """返回标题正好是 title 的开放 Issue 编号，没有则 None。"""
    r = sh([GH, "issue", "list", "--state", "open", "--json", "number,title", "--jq",
            f'.[] | select(.title == "{title}") | .number'])
    return r.stdout.strip().splitlines()[0] if r.stdout.strip() else None


def push(message: str) -> bool:
    """提交并推送当天产物（最多试 3 次，每次先同步远端）。"""
    # 只添加存在的文件：pathspec 不存在时 git add 会整条失败，什么都不加
    paths = [p for p in ("summaries/", "briefs.json", "README.md", "papers.json",
                         ".github/daily_issue.md", ".github/issue_title.txt") if os.path.exists(p)]
    sh(["git", "add", *paths])
    sh(["git", "commit", "-m", message])
    for _ in range(3):
        sh(["git", "pull", "--rebase", "origin", "main"])
        if sh(["git", "push"]).returncode == 0:
            print("  ✓ 已推送到 GitHub")
            return True
        time.sleep(5)
    print("  ⚠ 推送失败：改动留在本地，下次运行会一起推上去")
    return False


def publish_briefs(today: str):
    """--briefs-only 的收尾：推送表格和简介缓存，并把当天日报 Issue 的正文换成新表格。"""
    push(f"🈶 中文简介 {today}")
    number = find_issue(f"📚 论文日报 - {today}")
    if number is None:
        print("  ⚠ 当天还没有日报 Issue，之后创建时会直接用新表格")
        return
    r = sh([GH, "issue", "edit", number, "--body-file", prepare_issue_body()])
    print(f"  ✓ 已把 Issue #{number} 的正文换成中文表格" if r.returncode == 0
          else f"  ⚠ 更新 Issue #{number} 失败: {(r.stderr or r.stdout)[:150]}")


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

    push(f"🤖 深度解读 {today}（{count} 篇）")

    # ③ 评论当天 Issue；云端已停（省 Actions 费用），当天 Issue 不存在且数据新鲜时由本地创建
    title = f"📚 论文日报 - {today}"
    number = find_issue(title)
    if number is None:
        try:
            fresh = json.load(open("papers.json", encoding="utf-8")).get("date") == today
        except Exception:
            fresh = False
        if fresh:
            auth = sh([GH, "auth", "status"])
            if auth.returncode != 0:
                print(f"  ✗ gh 认证不可用（定时任务环境）: {auth.stderr[:150]}")
            sh([GH, "label", "create", "daily", "--color", "0E8A16", "--force"])
            body_file = prepare_issue_body()
            c = sh([GH, "issue", "create", "--title", title, "--label", "daily",
                    "--body-file", body_file])
            if c.returncode == 0:
                print("  ✓ 云端已停，本地已代发当天日报 Issue")
                number = find_issue(title)
            else:
                print(f"  ✗ Issue 创建失败: {(c.stderr or c.stdout)[-250:]}")
        else:
            print("  ⚠ 数据非今日（补抓失败），不创建 Issue 以免发旧内容")
    if number:
        r2 = sh([GH, "issue", "comment", number, "--body-file", path])
        print(f"  ✓ 已评论 Issue #{number}" if r2.returncode == 0 else f"  ⚠ Issue 评论失败: {r2.stderr[:100]}")
    else:
        print("  ⚠ 未找到当天 Issue，跳过评论（summaries 已存档）")


def write_briefs(data: dict, env: dict):
    """给表格里的全部论文补齐中文简介 + 星级（批量调用），然后重写 README / Issue 正文。

    放在精读之前：即使后面精读失败，表格也已经是中文的。
    简介按 arXiv 编号缓存在 briefs.json，已有简介的论文不重复生成。
    """
    import briefs as briefs_mod
    import main as main_mod
    papers = briefs_mod.all_papers(data)
    existing = briefs_mod.load_briefs()
    have = sum(1 for p in papers if p["arxiv_id"] in existing)
    print(f"[简介] 表格共 {len(papers)} 篇，已有 {have} 篇，需新生成 {len(papers) - have} 篇"
          f"（每 {briefs_mod.BATCH_SIZE} 篇一次调用）")
    result = existing
    if have < len(papers):
        result = briefs_mod.generate_briefs(
            papers, lambda prompt, max_tokens: chat(env, prompt, max_tokens, thinking=False), existing,
            on_progress=briefs_mod.save_briefs)  # 每批成功即落盘，中途崩了也不丢已花的钱
        briefs_mod.save_briefs(result)
        missing = sum(1 for p in papers if p["arxiv_id"] not in result)
        print(f"[简介] 新增 {len(result) - len(existing)} 篇"
              + (f"，{missing} 篇没生成成功，下次运行自动补" if missing else "，表格全部覆盖"))
    main_mod.render(data, result)  # 纯本地重写表格：不联网，不重新抓取


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=int, metavar="N", help="只分析前 N 篇（省额度）")
    parser.add_argument("--force", action="store_true", help="今天已分析过也重跑")
    parser.add_argument("--briefs-only", action="store_true",
                        help="只生成/更新中文简介并重写表格，不做全文精读")
    args = parser.parse_args()

    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    out_path = os.path.join(SUMMARY_DIR, f"{today}.md")
    if os.path.exists(out_path) and not args.force and not args.briefs_only:
        print(f"✓ {today} 已分析过（{out_path}），如需重跑加 --force")
        return

    env = load_env()
    print(f"=== 本地论文智能体 {today} | 模型 {env['LLM_MODEL']} ===")
    data = heal_if_needed(pull_papers())
    try:
        write_briefs(data, env)
    except Exception as e:
        print(f"⚠ 中文简介生成失败，表格暂用英文摘要: {e}")
    if args.briefs_only:
        publish_briefs(today)
        print("✅ 简介已更新（--briefs-only，未做全文精读）")
        return
    data = json.load(open("papers.json", encoding="utf-8"))  # 重读（heal 可能已更新）
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
            md.append(f"## 🧭 今日阅读指引\n\n{synthesize(digests, env)}\n\n---\n")
        except Exception as e:
            print(f"⚠ 综述生成失败: {e}")
    for d in digests:
        md.append(d["analysis"] + "\n---\n")
    md.append(f"\n*分析时间：{datetime.now(ZoneInfo('Asia/Shanghai')):%Y-%m-%d %H:%M}*\n")

    publish(today, "\n".join(md), len(digests))
    print(f"✅ 完成：{out_path}")


if __name__ == "__main__":
    main()
