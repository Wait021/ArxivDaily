# -*- coding: utf-8 -*-
"""全部可调配置。改完 git push 上去，第二天生效。"""

# ============ 论文追踪关键词 ============
# 每个关键词会同时在 arXiv 的【标题】和【摘要】里做短语搜索，按最近更新时间排序。
# 三条调研主线：①翻译/PPT 智能体 ②生物智能体 ③教学智能体
KEYWORDS = [
    # --- 主线①：翻译智能体（核心方向）---
    "Translation Agent",                   # 翻译智能体
    "LLM Translation",                     # 大模型翻译
    "Machine Translation",                 # 机器翻译（领域大方向）
    "Document-Level Machine Translation",  # 篇章级翻译：PPT/XML 等富文档翻译的基础
    "Slide Generation",                    # PPT/幻灯片生成
    "Slide Understanding",                 # PPT/幻灯片理解
    # --- 主线②：生物智能体（AI for Biology）---
    "AI for Biology",                      # 生物领域 AI（宽口径）
    "Drug Discovery",                      # 药物发现（生物 Agent 最大应用面）
    "Scientific Agent",                    # 科学研究 Agent（生物/化学/材料实验自动化）
    # --- 主线③：教学智能体（AI Tutoring）---
    "Educational Agent",                   # 教育 Agent
    "Tutoring Agent",                      # 辅导/导师 Agent
    "Intelligent Tutoring",                # 智能辅导系统（经典教育技术词，LLM 新方向）
    # --- 通用 Agent 技术 ---
    "LLM Agent",                           # Agent 大方向
    "Tool Use",                            # 工具调用（Agent 核心能力）
]

# 每个关键词最多从 arXiv 抓多少篇
MAX_RESULTS_PER_KEYWORD = 25
# README 里每个关键词最多展示多少篇
KEEP_PER_KEYWORD = 20
# 日报 Issue 里每个关键词最多放多少篇（README 不受此限制，放 KEEP_PER_KEYWORD 篇）。
# Issue 正文有 65536 字符的上限：每条筛选笔记连同标题、链接大约 470 个字符，
# 14 个关键词 × 8 篇 + 热门榜 12 篇刚好放得下；调大到 10 篇，最后两个分区就会被截掉。
ISSUE_RESULTS_PER_KEYWORD = 8

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

# 你的研究方向画像（三条主线），会注入总结 prompt，让 AI 顺便给论文标注与你的相关度
RESEARCH_PROFILE = (
    "我的研究方向有三条主线：①翻译智能体（Translation Agent）——特别是 PPT/幻灯片、"
    "XML 等富结构文档的 LLM 自动翻译，以及文档级机器翻译的评测与智能体化；"
    "②生物智能体（AI for Biology）——生物医药领域的 LLM Agent，如药物发现、"
    "实验规划与自动化科研；③教学智能体（AI Tutoring）——教育领域的 Agent、"
    "个性化辅导与智能教学系统。通用技术兴趣：LLM Agent、工具调用（Tool Use）、"
    "多智能体协作与评测。"
)

# ============ 输出 ============
README_INTRO = (
    "本仓库每天 11:00 由本地程序自动更新：抓取 arXiv 关键词论文 + Hugging Face 本周热门论文。\n\n"
    "表格里每篇论文有一条大模型根据**摘要**写的筛选笔记，分三段：**做法**、**作者报告**"
    "（摘要里的结果和数字，是作者的声称，不是已经证实的结论）、**判断**（一眼能看出的局限，或和我的关系）。"
    "筛选笔记只读摘要不读全文，所以它不能代替对证据的核查。\n\n"
    "**相关度**：⭐⭐⭐⭐⭐ 论文本身就在做我的研究方向；⭐⭐⭐⭐ 不做这些方向，但方法或工具能直接用上；"
    "⭐⭐⭐ 有间接借鉴；⭐⭐ 只是同属一个大领域；⭐ 基本无关。\n\n"
    "每天另有 8 篇论文的**全文精读**（逐条核查主张与证据），在当天 Issue 的评论里。"
    "README 的表格点开可展开英文原摘要。\n\n"
    "点右上角 **Watch** → **Custom** → 勾选 **Issues** 可以每天收到邮件通知。\n\n"
    "关键词、数量等配置在 [`config.py`](config.py) 里修改。"
)
