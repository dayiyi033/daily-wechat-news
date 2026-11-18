import os
import json
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
import time
import socket
import ssl
from datetime import datetime, date
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo


# ============================================================
# 一、基础配置
# ============================================================

TZ = ZoneInfo("Asia/Shanghai")
US_TZ = ZoneInfo("America/New_York")

LAT = 34.3416
LON = 108.9398

# 国内新闻优先，国际新闻只保留重大事件
DOMESTIC_NEWS_LIMIT = 6
INTERNATIONAL_NEWS_LIMIT = 3

NEWS_QUERIES = {
    "国内热点": (
        "中国 国内 重大政策 社会热点 经济 科技 重要新闻"
    ),
    "国际重大新闻": (
        "国际 重大事件 战争 冲突 地缘政治 全球经济 重大灾害"
    ),
}

# 国际新闻必须命中至少一个重大事件关键词才会进入早报。
# 这是规则筛选，不代表自动判断绝对准确；后续可根据实际推送效果调整。
INTERNATIONAL_MAJOR_KEYWORDS = (
    "战争", "开战", "军事冲突", "武装冲突", "袭击", "入侵",
    "停火", "和平协议", "核", "制裁", "政变", "选举结果",
    "总统", "首相", "峰会", "央行", "美联储", "降息", "加息",
    "金融危机", "全球经济", "贸易战", "关税",
    "地震", "海啸", "飓风", "台风", "疫情", "重大事故",
    "人工智能", "芯片禁令", "出口管制", "重大突破",
    "联合国", "北约", "欧盟", "中东", "俄乌", "巴以",
)

# 财经模块只保留纳斯达克100和上海黄金交易所 Au99.99
US_INDEXES = [
    ("纳斯达克100", "^NDX"),
]

# 黄金数据超过两个工作日仍未更新时，标记为过期。
GOLD_MAX_BUSINESS_DAYS_OLD = 2


# ============================================================
# 二、通用 HTTP 请求
# ============================================================

def http_get(url, timeout=45, retries=3):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/xml,application/rss+xml,text/html,*/*",
        },
    )

    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")

        except urllib.error.HTTPError:
            raise

        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ssl.SSLError,
        ) as error:
            if attempt == retries:
                print(
                    f"HTTP 请求最终失败，已重试 {retries} 次："
                    f"{type(error).__name__}: {error}"
                )
                raise
