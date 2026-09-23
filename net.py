# -*- coding: utf-8 -*-
"""统一的 HTTP 请求工具。

经验教训（在国内开发机上）：
  - arxiv.org / export.arxiv.org 直连正常，走代理反而会被破坏 TLS 证书链 → 用 direct_get
  - huggingface.co 直连不通，必须走系统代理 → 用 proxy_get（默认 opener 自动识别）
  - GitHub Actions（美国服务器）没有代理环境，两种方式都等价于直连
"""
import urllib.request

# 带浏览器 UA，降低被拒概率
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) ArxivDaily-Agent/1.0"}

_direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_default_opener = urllib.request.build_opener()


def get(url: str, timeout: int = 60, direct: bool = False, headers: dict = None) -> bytes:
    """GET 请求。direct=True 强制不走任何代理；headers 可覆盖默认 UA。"""
    opener = _direct_opener if direct else _default_opener
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    return opener.open(req, timeout=timeout).read()
