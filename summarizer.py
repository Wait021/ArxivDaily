# -*- coding: utf-8 -*-
"""调用 OpenAI 兼容接口的大模型，阅读论文全文生成中文总结。

环境变量（GitHub Actions 里配成 repo secrets，本地跑直接 export）：
  LLM_API_KEY   必填，不配则自动跳过 AI 总结
  LLM_BASE_URL  默认 https://open.bigmodel.cn/api/paas/v4 （智谱 GLM）
  LLM_MODEL     默认 glm-4.6
"""
import html
import json
import os
import re
import time
import urllib.request

import config
import net

_SUMMARY_PROMPT = """我的研究背景：{profile}

请阅读下面这篇论文（若无全文则只有摘要），用中文输出：
1. **一句话总结**
2. **核心方法**（2-3 句）
3. **关键结果**（1-2 句）
4. **相关度**：⭐1-5 星 + 一句理由（从我的研究背景出发）

除相关度行外正文控制在 150 字以内。直接输出内容，不要前后寒暄。

论文标题：{title}

论文内容：
{body}"""


def llm_enabled() -> bool:
    return bool(os.environ.get("LLM_API_KEY", "").strip())


def _chat(cfg: dict, prompt: str) -> str:
    """调用 /chat/completions，带重试。"""
    payload = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 800,
    }).encode("utf-8")
    req = urllib.request.Request(
        cfg["base_url"] + "/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["key"],
        },
    )
    last_err = None
    for _ in range(3):
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=180).read().decode("utf-8"))
            return resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            last_err = e
            time.sleep(5)
    raise RuntimeError(f"LLM 调用失败: {last_err}")


def fetch_fulltext(arxiv_id: str) -> str:
    """抓论文全文：优先 arXiv 官方 HTML 版，其次 ar5iv，都失败返回空串。"""
    for url in (f"https://arxiv.org/html/{arxiv_id}", f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"):
        try:
            # arxiv.org 直连（代理可能破坏证书链）
            raw = net.get(url, timeout=60, direct=True).decode("utf-8", errors="ignore")
            # 去 script/style，去标签，压缩空白
            raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", raw)
            text = html.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 2000:  # 太短的说明没有正文
                return text[:config.FULLTEXT_MAX_CHARS]
        except Exception:
            continue
    return ""


def summarize_paper(paper: dict) -> str:
    """给单篇论文生成中文总结；失败或未配置 key 时返回空串（调用方回退到原始摘要）。"""
    if not llm_enabled():
        return ""
    cfg = {
        "key": os.environ["LLM_API_KEY"].strip(),
        "base_url": os.environ.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/"),
        "model": os.environ.get("LLM_MODEL", "glm-4.6"),
    }
    fulltext = fetch_fulltext(paper["arxiv_id"])
    body = fulltext if fulltext else ("摘要：" + paper.get("abstract", ""))
    prompt = _SUMMARY_PROMPT.format(profile=config.RESEARCH_PROFILE, title=paper["title"], body=body)
    try:
        return _chat(cfg, prompt)
    except Exception as e:
        print(f"    总结失败（{paper['title'][:40]}...）: {e}")
        return ""
