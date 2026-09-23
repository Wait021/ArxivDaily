# -*- coding: utf-8 -*-
"""全部可调配置。改完 git push 上去，第二天生效。"""

# ============ 论文追踪关键词 ============
# 每个关键词会同时在 arXiv 的【标题】和【摘要】里做短语搜索，按最近更新时间排序。
# 想增删直接改这个列表即可。
KEYWORDS = [
    "Translation Agent",                   # 翻译智能体（核心方向）
    "LLM Translation",                     # 大模型翻译
    "Machine Translation",                 # 机器翻译（领域大方向）
    "Document-Level Machine Translation",  # 篇章级翻译：PPT/XML 等富文档翻译的基础
    "Slide Generation",                    # PPT/幻灯片生成
    "Slide Understanding",                 # PPT/幻灯片理解
    "LLM Agent",                           # Agent 大方向
    "Tool Use",                            # 工具调用（Agent 核心能力）
]

# 每个关键词最多从 arXiv 抓多少篇
MAX_RESULTS_PER_KEYWORD = 25
# README 里每个关键词最多展示多少篇
KEEP_PER_KEYWORD = 20
# 每日 Issue 推送里每个关键词最多多少篇（Issue 是你每天看的，宁精勿滥）
ISSUE_RESULTS_PER_KEYWORD = 10

# ============ 本周热门论文（Hugging Face Trending）============
TRENDING_DAYS = 7    # 统计最近几天的热门
TRENDING_TOP_N = 12  # 按点赞数取前 N 篇

# ============ AI 总结（大模型阅读论文全文）============
# 通过环境变量注入（GitHub Actions 里配成 repo secrets）：
#   LLM_API_KEY   必填，不配则自动跳过 AI 总结、只用原始摘要
#   LLM_BASE_URL  OpenAI 兼容接口地址，默认智谱 GLM
#   LLM_MODEL     模型名，默认 glm-4.6
# 可选的兼容服务举例：
#   智谱 GLM   https://open.bigmodel.cn/api/paas/v4      glm-4.6 / glm-4-flash
#   DeepSeek   https://api.deepseek.com/v1               deepseek-chat
#   Kimi       https://api.moonshot.cn/v1                moonshot-v1-128k
#   OpenAI     https://api.openai.com/v1                 gpt-4o-mini
SUMMARIZE_PER_KEYWORD = 5   # 每个关键词给前几篇生成 AI 全文中文总结
SUMMARIZE_TRENDING = 8      # 热门榜里给前几篇生成 AI 总结
FULLTEXT_MAX_CHARS = 30000  # 论文全文最多截取多少字符喂给模型（控制 token 花费）

# 你的研究方向画像，会注入总结 prompt，让 AI 顺便给论文标注与你的相关度
RESEARCH_PROFILE = (
    "我的研究方向是翻译智能体（Translation Agent），特别是 PPT/幻灯片、XML 等"
    "富结构文档的 LLM 自动翻译，以及 LLM Agent、工具调用（Tool Use）相关技术。"
)

# ============ 输出 ============
README_INTRO = (
    "本仓库由 GitHub Actions 每天自动更新：抓取 arXiv 关键词论文 + "
    "Hugging Face 本周热门论文，并调用大模型阅读论文全文生成中文总结。\n\n"
    "点右上角 **Watch** → **Custom** → 勾选 **Issues** 可以每天收到邮件推送。\n\n"
    "关键词、数量、模型等配置全部在 [`config.py`](config.py) 里修改。"
)
