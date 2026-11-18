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

            wait_seconds = 2 ** attempt
            print(
                f"HTTP 请求失败，第 {attempt} 次尝试，"
                f"{wait_seconds} 秒后重试：{repr(error)}"
            )
            time.sleep(wait_seconds)


# ============================================================
# 三、天气模块：西安
# ============================================================

def get_weather():
    params = {
        "latitude": LAT,
        "longitude": LON,
        "daily": (
            "weather_code,"
            "temperature_2m_max,"
            "temperature_2m_min,"
            "precipitation_probability_max,"
            "wind_speed_10m_max"
        ),
        "timezone": "Asia/Shanghai",
        "forecast_days": 1,
    }

    url = (
        "https://api.open-meteo.com/v1/forecast?"
        + urllib.parse.urlencode(params)
    )

    print("开始请求 Open-Meteo 天气接口...")
    data = json.loads(http_get(url))
    daily = data.get("daily")

    if not daily:
        raise RuntimeError(f"天气接口没有返回 daily 数据：{data}")

    weather_map = {
        0: "晴",
        1: "大部晴朗",
        2: "局部多云",
        3: "阴天",
        45: "有雾",
        48: "雾凇",
        51: "小毛毛雨",
        53: "毛毛雨",
        55: "较强毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        80: "阵雨",
        81: "较强阵雨",
        82: "强阵雨",
        95: "雷暴",
        96: "雷暴伴小冰雹",
        99: "雷暴伴强冰雹",
    }

    try:
        code = int(daily["weather_code"][0])
        t_max = daily["temperature_2m_max"][0]
        t_min = daily["temperature_2m_min"][0]
        rain = daily["precipitation_probability_max"][0]
        wind = daily["wind_speed_10m_max"][0]
        forecast_date = daily["time"][0]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise RuntimeError(f"天气数据格式异常：{error}")

    weather = weather_map.get(code, "天气状况未知")

    return (
        f"**天气：** {weather}\n"
        f"**气温：** {t_min}℃ ~ {t_max}℃\n"
        f"**降水概率：** {rain}%\n"
        f"**最大风速：** {wind} km/h\n"
        f"**预报日期：** {forecast_date}\n"
    )


# ============================================================
# 四、新闻模块：Google News RSS
# ============================================================

def parse_news_date(value):
    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        return parsed.astimezone(TZ)
    except (TypeError, ValueError, OverflowError):
        return None


def get_news(query, limit):
    params = {
        "q": query + " when:1d",
        "hl": "zh-CN",
        "gl": "CN",
        "ceid": "CN:zh-Hans",
    }

    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode(params)
    )

    root = ET.fromstring(http_get(url))
    results = []
    seen = set()

    for item in root.findall("./channel/item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        pub_date_text = item.findtext("pubDate", "").strip()
        pub_date = parse_news_date(pub_date_text)

        source_node = item.find("source")
        source = (
            source_node.text.strip()
            if source_node is not None and source_node.text
            else "新闻来源"
        )

        if not title or not link or title in seen:
            continue

        # 不让 RSS 中明显过旧的新闻混入当天早报。
        if pub_date:
            age_hours = (
                datetime.now(TZ) - pub_date
            ).total_seconds() / 3600
            if age_hours > 36:
                continue

        seen.add(title)
        results.append({
            "title": title,
            "source": source,
            "link": link,
            "published": pub_date,
        })

        if len(results) >= limit * 3:
            break

    return results


def is_major_international_news(news):
    title = news["title"]
    return any(keyword in title for keyword in INTERNATIONAL_MAJOR_KEYWORDS)


def append_news_section(lines, title, query, limit, major_only=False):
    lines.extend([f"### {title}", ""])

    try:
        news_list = get_news(query, limit)

        if major_only:
            news_list = [
                item for item in news_list
                if is_major_international_news(item)
            ]

        news_list = news_list[:limit]

        if not news_list:
            if major_only:
                lines.append("今日暂无符合重大事件筛选条件的国际新闻。")
            else:
                lines.append("暂无符合条件的资讯。")
            lines.append("")
            return

        for index, news in enumerate(news_list, start=1):
            published_text = ""
            if news["published"]:
                published_text = (
                    f"（{news['published'].strftime('%m-%d %H:%M')}）"
                )

            lines.append(
                f"{index}. [{news['title']}]({news['link']})"
                f" — {news['source']}{published_text}"
            )

        lines.append("")

    except Exception as error:
        print(
            f"{title} 获取失败："
            f"{type(error).__name__}: {error}"
        )
        lines.append("本栏目暂时无法获取。")
        lines.append("")


# ============================================================
# 五、美股行情模块：仅纳斯达克100
# ============================================================

def get_us_index(symbol):
    encoded_symbol = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{encoded_symbol}?range=10d&interval=1d"
    )

    data = json.loads(http_get(url))
    chart = data.get("chart", {})

    if chart.get("error"):
        raise RuntimeError(str(chart["error"]))

    results = chart.get("result")
    if not results:
        raise RuntimeError(f"{symbol} 没有返回行情数据")

    result = results[0]
    timestamps = result.get("timestamp", [])
    quote_data = (
        result.get("indicators", {})
        .get("quote", [{}])[0]
    )
    closes = quote_data.get("close", [])

    records = []
    for timestamp, close in zip(timestamps, closes):
        if close is None:
            continue
        records.append({
            "timestamp": int(timestamp),
            "close": float(close),
        })

    records.sort(key=lambda item: item["timestamp"])

    if len(records) < 2:
        raise RuntimeError(f"{symbol} 有效收盘数据不足")

    previous = records[-2]
    latest = records[-1]

    previous_close = previous["close"]
    latest_close = latest["close"]

    change = latest_close - previous_close
    change_pct = (
        change / previous_close * 100
        if previous_close != 0 else 0
    )

    trade_datetime = datetime.fromtimestamp(
        latest["timestamp"], US_TZ
    )
    fetched_at = datetime.now(TZ)

    # regularMarketTime 是 Yahoo 返回的行情时间；若缺失，则明确使用本次抓取时间，
    # 不把抓取时间冒充为交易所更新时间。
    meta = result.get("meta", {})
    market_timestamp = meta.get("regularMarketTime")
    market_update = None

    if market_timestamp:
        market_update = datetime.fromtimestamp(
            int(market_timestamp), TZ
        )

    return {
        "trade_date": trade_datetime.strftime("%Y-%m-%d"),
        "close": latest_close,
        "change": change,
        "change_pct": change_pct,
        "market_update": market_update,
        "fetched_at": fetched_at,
    }


def get_us_market():
    lines = []

    for name, symbol in US_INDEXES:
        try:
            item = get_us_index(symbol)

            lines.append(
                f"- **{name}：** {item['close']:,.2f} 点 "
                f"（较前一交易日 {item['change_pct']:+.2f}%）"
            )
            lines.append(
                f"  - 交易日期：{item['trade_date']}（美东时间）"
            )

            if item["market_update"]:
                lines.append(
                    "  - 行情更新时间："
                    f"{item['market_update'].strftime('%Y-%m-%d %H:%M:%S')} "
                    "（北京时间，Yahoo Finance）"
                )
            else:
                lines.append(
                    "  - 数据抓取时间："
                    f"{item['fetched_at'].strftime('%Y-%m-%d %H:%M:%S')} "
                    "（北京时间；非交易所更新时间）"
                )

            print(f"{name}行情获取成功：{item}")

        except Exception as error:
            print(
                f"{name}行情获取失败："
                f"{type(error).__name__}: {error}"
            )
            lines.append(f"- **{name}：** 暂时无法获取行情")

    return lines


# ============================================================
# 六、黄金行情模块：上海黄金交易所 Au99.99
# ============================================================

def parse_trade_date(value):
    if value is None:
        return None

    text = str(value).strip()
    formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y%m%d",
        "%Y年%m月%d日",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    )

    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    return None


def business_days_between(start_date, end_date):
    """计算 start_date 之后到 end_date（含）之间的工作日数量，不含周末。"""
    count = 0
    current = start_date

    from datetime import timedelta
    while current < end_date:
        current += timedelta(days=1)
        if current.weekday() < 5:
            count += 1

    return count


def get_gold_close():
    url = "https://www.sge.com.cn/graph/Dailyhq"
    post_data = urllib.parse.urlencode({
        "instid": "Au99.99"
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=post_data,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.sge.com.cn/",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/javascript, */*",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        raw_text = response.read().decode("utf-8")

    data = json.loads(raw_text)
    raw_records = data.get("time", [])

    if not isinstance(raw_records, list):
        raise RuntimeError(
            f"上金所返回的数据格式异常，响应字段 time 不是数组：{data}"
        )

    records = []

    for row in raw_records:
        try:
            if isinstance(row, dict):
                trade_date_value = (
                    row.get("date")
                    or row.get("日期")
                    or row.get("交易日期")
                    or row.get("time")
                )
                close_value = (
                    row.get("close")
                    or row.get("收盘")
                    or row.get("收盘价")
                )

            elif isinstance(row, (list, tuple)):
                # 上金所历史数据常见格式：日期、开盘、收盘、最低、最高
                if len(row) < 3:
                    continue
                trade_date_value = row[0]
                close_value = row[2]
            else:
                continue

            trade_date = parse_trade_date(trade_date_value)
            if trade_date is None or close_value is None:
                continue

            close = float(close_value)
            if close <= 0:
                continue

            records.append({
                "date": trade_date,
                "close": close,
            })

        except (TypeError, ValueError):
            continue

    if not records:
        sample = raw_records[:3] if isinstance(raw_records, list) else raw_records
        raise RuntimeError(
            "未解析到 Au99.99 有效行情。"
            f"接口原始数据样例：{sample}"
        )

    # 使用真正的 date 对象排序，避免字符串格式不同造成排序错误。
    records.sort(key=lambda item: item["date"])

    # 同一交易日如果出现多条记录，保留最后一条。
    deduplicated = {}
    for record in records:
        deduplicated[record["date"]] = record
    records = sorted(
        deduplicated.values(),
        key=lambda item: item["date"]
    )

    latest = records[-1]
    fetched_at = datetime.now(TZ)
    today = fetched_at.date()

    age_business_days = business_days_between(
        latest["date"], today
    )
    is_stale = age_business_days > GOLD_MAX_BUSINESS_DAYS_OLD

    if len(records) >= 2:
        previous = records[-2]
        change = latest["close"] - previous["close"]
        change_pct = (
            change / previous["close"] * 100
            if previous["close"] != 0 else 0
        )
        change_text = (
            f"较前一交易日 {change:+.2f} 元/克，"
            f"{change_pct:+.2f}%"
        )
    else:
        change_text = "暂无前一交易日数据，无法计算涨跌幅"

    print(
        "Au99.99 数据诊断："
        f"接口记录数={len(raw_records)}，"
        f"有效记录数={len(records)}，"
        f"最新交易日={latest['date']}，"
        f"抓取时间={fetched_at.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    status = "数据可能滞后，请勿视为当日最新行情" if is_stale else "最近有效交易日行情"

    return (
        f"- **Au99.99：** {latest['close']:.2f} 元/克\n"
        f"- **涨跌：** {change_text}\n"
        f"- **行情日期：** {latest['date'].isoformat()}（上金所交易日期）\n"
        f"- **抓取时间：** {fetched_at.strftime('%Y-%m-%d %H:%M:%S')}（北京时间）\n"
        f"- **数据状态：** {status}"
    )


# ============================================================
# 七、生成完整早报
# ============================================================

def build_message():
    now = datetime.now(TZ)

    lines = [
        "# 每日资讯早报",
        (
            f"> {now.strftime('%Y年%m月%d日')} 星期"
            f"{'一二三四五六日'[now.weekday()]}"
        ),
        f"> 生成时间：{now.strftime('%H:%M:%S')}（北京时间）",
        "",
        "## 一、今日天气 | 西安",
        "",
    ]

    try:
        lines.append(get_weather())
    except Exception as error:
        print(
            f"天气获取失败："
            f"{type(error).__name__}: {error}"
        )
        lines.append("天气数据暂时无法获取。")

    lines.extend([
        "",
        "## 二、国内热点新闻",
        "",
    ])

    append_news_section(
        lines,
        "国内重要资讯",
        NEWS_QUERIES["国内热点"],
        DOMESTIC_NEWS_LIMIT,
        major_only=False,
    )

    lines.extend([
        "",
        "## 三、国际重大新闻",
        "",
    ])

    append_news_section(
        lines,
        "国际重大事件（严格筛选）",
        NEWS_QUERIES["国际重大新闻"],
        INTERNATIONAL_NEWS_LIMIT,
        major_only=True,
    )

    lines.extend([
        "",
        "## 四、财经行情",
        "",
        "### （一）纳斯达克100",
        "",
    ])

    lines.extend(get_us_market())

    lines.extend([
        "",
        "### （二）黄金 Au99.99",
        "",
    ])

    try:
        lines.append(get_gold_close())
    except Exception as error:
        print(
            f"黄金行情获取失败："
            f"{type(error).__name__}: {error}"
        )
        lines.append(
            "- **Au99.99：** 暂时无法获取有效行情，未使用旧数据冒充最新价格。"
        )

    lines.extend([
        "",
        "---",
        (
            "> 数据来源：Open-Meteo、Google News RSS、"
            "Yahoo Finance、上海黄金交易所"
        ),
    ])

    return "\n".join(lines)


# ============================================================
# 八、微信公众号频道推送：WPush
# ============================================================

def send_wpush(message):
    """通过 WPush 公众号频道向已订阅用户发送早报。"""
    api_key = os.getenv("WPUSH_APIKEY")
    topic_code = os.getenv("WPUSH_TOPIC_CODE")

    if not api_key:
        raise RuntimeError("未配置 WPUSH_APIKEY")

    if not topic_code:
        raise RuntimeError("未配置 WPUSH_TOPIC_CODE")

    data = {
        "apikey": api_key,
        "title": "每日资讯早报",
        "content": message,
        "channel": "wechat",
        "topic_code": topic_code,
    }

    request = urllib.request.Request(
        "https://api.wpush.cn/api/v1/send",
        data=urllib.parse.urlencode(data).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise RuntimeError(
            f"WPush HTTP错误：{error.code}，{detail}"
        )

    if result.get("code") != 0:
        raise RuntimeError(f"WPush发送失败：{result}")

    print(
        "WPush消息提交成功，消息ID："
        f"{result.get('data')}"
    )


# ============================================================
# 九、程序入口
# ============================================================

if __name__ == "__main__":
    print("开始生成每日资讯早报...")

    message = build_message()

    print("\n========== 早报内容 ==========\n")
    print(message)
    print("\n========== 开始 WPush 公众号频道推送 ==========\n")

    send_wpush(message)

    print("\n每日资讯早报执行完成。")
