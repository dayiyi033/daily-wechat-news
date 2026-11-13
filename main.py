
import os
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

from datetime import datetime
from zoneinfo import ZoneInfo


# ============================================================
# 一、基础配置
# ============================================================

TZ = ZoneInfo("Asia/Shanghai")
US_TZ = ZoneInfo("America/New_York")

LAT = 34.3416
LON = 108.9398

NEWS_LIMIT = 3

NEWS_CATEGORIES = {
    "国内新闻": "中国 国内 新闻",
    "国际新闻": "国际 新闻",
    "科技资讯": "科技 互联网",
    "财经新闻": "财经 金融 市场",
    "AI行业动态": "人工智能 AI",
}

# 美股指数
US_INDEXES = [
    ("道琼斯", "^DJI"),
    ("纳斯达克", "^IXIC"),
    ("标普500", "^GSPC"),
]


# ============================================================
# 二、通用 HTTP 请求
# ============================================================

def http_get(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/xml, */*",
        }
    )

    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read()


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

    try:
        print("开始请求 Open-Meteo 天气接口...")

        response = http_get(url)

        print("天气接口响应成功，开始解析数据...")

        data = json.loads(response)

    except Exception as e:
        print(
            f"Open-Meteo 请求异常："
            f"{type(e).__name__}: {repr(e)}"
        )
        raise

    daily = data.get("daily")

    if not daily:
        raise RuntimeError(
            f"天气接口没有返回 daily 数据：{data}"
        )

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

    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise RuntimeError(f"天气数据格式异常：{e}")

    weather = weather_map.get(code, "天气状况未知")

    return (
        f"**天气：** {weather}\n"
        f"**气温：** {t_min}℃ ~ {t_max}℃\n"
        f"**降水概率：** {rain}%\n"
        f"**最大风速：** {wind} km/h\n"
    )


# ============================================================
# 四、新闻模块：Google News RSS
# ============================================================

def get_news(query):

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

        source_node = item.find("source")

        source = (
            source_node.text.strip()
            if source_node is not None and source_node.text
            else "新闻来源"
        )

        if not title or not link or title in seen:
            continue

        seen.add(title)

        results.append({
            "title": title,
            "source": source,
            "link": link,
        })

        if len(results) >= NEWS_LIMIT:
            break

    return results


# ============================================================
# 五、美股行情模块：Yahoo Finance
# ============================================================

def get_us_index(symbol):

    encoded_symbol = urllib.parse.quote(
        symbol,
        safe=""
    )

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
            "timestamp": timestamp,
            "close": float(close),
        })

    records.sort(key=lambda x: x["timestamp"])

    if len(records) < 2:
        raise RuntimeError(f"{symbol} 有效收盘数据不足")

    previous = records[-2]
    latest = records[-1]

    previous_close = previous["close"]
    latest_close = latest["close"]

    change = latest_close - previous_close

    change_pct = (
        change / previous_close * 100
        if previous_close != 0
        else 0
    )

    market_date = datetime.fromtimestamp(
        latest["timestamp"],
        US_TZ
    ).strftime("%Y-%m-%d")

    return {
        "date": market_date,
        "close": latest_close,
        "change": change,
        "change_pct": change_pct,
    }


def get_us_market():

    lines = []

    for name, symbol in US_INDEXES:

        try:

            item = get_us_index(symbol)

            lines.append(
                f"- **{name}：** "
                f"{item['close']:,.2f} 点 "
                f"（{item['change_pct']:+.2f}%）"
            )

            print(
                f"{name}行情获取成功："
                f"{item}"
            )

        except Exception as e:

            print(
                f"{name}行情获取失败："
                f"{type(e).__name__}: {e}"
            )

            lines.append(
                f"- **{name}：** 暂时无法获取"
            )

    return lines


# ============================================================
# 六、黄金行情模块：上海黄金交易所 Au99.99
# ============================================================

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

    with urllib.request.urlopen(
        request,
        timeout=25
    ) as response:

        data = json.loads(
            response.read().decode("utf-8")
        )

    raw_records = data.get("time", [])

    if not isinstance(raw_records, list):
        raise RuntimeError(
            f"上金所返回的数据格式异常：{data}"
        )

    records = []

    for row in raw_records:

        try:

            if isinstance(row, dict):

                trade_date = (
                    row.get("date")
                    or row.get("日期")
                    or row.get("交易日期")
                )

                close = (
                    row.get("close")
                    or row.get("收盘")
                    or row.get("收盘价")
                )

            elif isinstance(row, (list, tuple)):

                # 上金所历史数据格式：
                # 日期、开盘、收盘、最低、最高
                if len(row) < 3:
                    continue

                trade_date = row[0]
                close = row[2]

            else:
                continue

            if not trade_date or close is None:
                continue

            close = float(close)

            if close <= 0:
                continue

            records.append({
                "date": str(trade_date),
                "close": close,
            })

        except (TypeError, ValueError):
            continue

    # 按交易日期排序
    records.sort(key=lambda x: x["date"])

    if not records:
        raise RuntimeError(
            f"没有获取到 Au99.99 有效收盘数据：{data}"
        )

    latest = records[-1]

    print(
        "Au99.99 最新收盘数据：",
        latest
    )

    # 有前一个交易日的数据时，计算涨跌
    if len(records) >= 2:

        previous = records[-2]

        change = (
            latest["close"] - previous["close"]
        )

        change_pct = (
            change / previous["close"] * 100
            if previous["close"] != 0
            else 0
        )

        change_text = (
            f"（较前一交易日 "
            f"{change:+.2f} 元，"
            f"{change_pct:+.2f}%）"
        )

    else:

        change_text = ""

    return (
        f"- **Au99.99：** "
        f"{latest['close']:.2f} 元/克 "
        f"{change_text}\n"
        f"- **交易日期：** {latest['date']}"
    )


# ============================================================
# 七、新闻栏目通用排版
# ============================================================

def append_news_section(lines, title, category):

    lines.extend([
        f"### {title}",
        "",
    ])

    try:

        news_list = get_news(
            NEWS_CATEGORIES[category]
        )

        if not news_list:

            lines.append("暂无符合条件的资讯。")
            lines.append("")
            return

        for i, news in enumerate(
            news_list,
            start=1
        ):

            lines.append(
                f"{i}. [{news['title']}]({news['link']})"
            )

        lines.append("")

    except Exception as e:

        print(
            f"{category} 获取失败："
            f"{type(e).__name__}: {e}"
        )

        lines.append("本栏目暂时无法获取。")
        lines.append("")


# ============================================================
# 八、生成完整早报
# ============================================================

def build_message():

    now = datetime.now(TZ)

    lines = [
        "# 每日资讯早报",

        f"> {now.strftime('%Y年%m月%d日')} 星期"
        f"{'一二三四五六日'[now.weekday()]}",

        "",
        "## 一、今日天气 | 西安",
        "",
    ]

    # --------------------------------------------------------
    # 第一部分：天气
    # --------------------------------------------------------

    try:

        lines.append(get_weather())

    except Exception as e:

        print(
            f"天气获取失败："
            f"{type(e).__name__}: {e}"
        )

        lines.append("天气数据暂时无法获取。")

    # --------------------------------------------------------
    # 第二部分：新闻
    # --------------------------------------------------------

    lines.extend([
        "",
        "## 二、新闻",
        "",
    ])

    append_news_section(
        lines,
        "（一）国内新闻",
        "国内新闻"
    )

    append_news_section(
        lines,
        "（二）国际新闻",
        "国际新闻"
    )

    # --------------------------------------------------------
    # 第三部分：财经与科技
    # --------------------------------------------------------

    lines.extend([
        "",
        "## 三、财经与科技",
        "",
        "### （一）昨夜美股收盘",
        "",
    ])

    # 美股行情
    try:

        lines.extend(
            get_us_market()
        )

    except Exception as e:

        print(
            f"美股行情获取失败："
            f"{type(e).__name__}: {e}"
        )

        lines.append("美股行情暂时无法获取。")

    # 黄金行情
    lines.extend([
        "",
        "### （二）黄金行情",
        "",
    ])

    try:

        lines.append(
            get_gold_close()
        )

    except Exception as e:

        print(
            f"黄金行情获取失败："
            f"{type(e).__name__}: {e}"
        )

        lines.append(
            "Au99.99 收盘数据暂时无法获取。"
        )

    # 财经新闻
    append_news_section(
        lines,
        "（三）财经新闻",
        "财经新闻"
    )

    # 科技资讯
    append_news_section(
        lines,
        "（四）科技资讯",
        "科技资讯"
    )

    # AI 行业动态
    append_news_section(
        lines,
        "（五）AI 行业动态",
        "AI行业动态"
    )

    # --------------------------------------------------------
    # 数据来源
    # --------------------------------------------------------

    lines.extend([
        "---",
        "> 数据来源：Open-Meteo、Google News RSS、"
        "Yahoo Finance、上海黄金交易所",
    ])

    return "\n".join(lines)


# ============================================================
# 九、微信推送模块：WPush
# ============================================================

def send_wecom(message):

    api_key = os.getenv("WPUSH_APIKEY")
    topic_code = os.getenv("WPUSH_TOPIC_CODE")

    if not api_key:
        raise RuntimeError(
            "未配置 WPUSH_APIKEY"
        )

    if not topic_code:
        raise RuntimeError(
            "未配置 WPUSH_TOPIC_CODE"
        )

    data = {
        "apikey": api_key,
        "title": "每日资讯早报",
        "content": message,
        "channel": "wechat",
        "topic_code": topic_code,
    }

    request = urllib.request.Request(
        "https://api.wpush.cn/api/v1/send",

        data=urllib.parse.urlencode(
            data
        ).encode("utf-8"),

        headers={
            "Content-Type": (
                "application/x-www-form-urlencoded"
            )
        },

        method="POST",
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            result = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as error:

        detail = error.read().decode(
            "utf-8",
            "replace"
        )

        raise RuntimeError(
            f"WPush HTTP错误：{error.code}，{detail}"
        )

    if result.get("code") != 0:

        raise RuntimeError(
            f"WPush发送失败：{result}"
        )

    print(
        f"WPush消息提交成功，消息ID："
        f"{result.get('data')}"
    )


# ============================================================
# 十、程序入口
# ============================================================

if __name__ == "__main__":

    print("开始生成每日资讯早报...")

    message = build_message()

    print("\n========== 早报内容 ==========\n")
    print(message)
    print("\n========== 开始微信推送 ==========\n")

    send_wecom(message)

    print("\n每日资讯早报执行完成。")
