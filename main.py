
import os
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

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


def http_get(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DailyNewsBot/1.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read()


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
        print(f"Open-Meteo 请求异常：{type(e).__name__}: {repr(e)}")
        raise
        daily = data["daily"]

    weather_map = {
        0: "晴", 1: "大部晴朗", 2: "局部多云",
        3: "阴天", 45: "有雾", 48: "雾凇",
        51: "小毛毛雨", 53: "毛毛雨", 55: "较强毛毛雨",
        61: "小雨", 63: "中雨", 65: "大雨",
        71: "小雪", 73: "中雪", 75: "大雪",
        80: "阵雨", 81: "较强阵雨", 82: "强阵雨",
        95: "雷暴", 96: "雷暴伴小冰雹",
        99: "雷暴伴强冰雹",
    }

    code = daily["weather_code"][0]
    weather = weather_map.get(code, "天气状况未知")

    t_max = daily["temperature_2m_max"][0]
    t_min = daily["temperature_2m_min"][0]
    rain = daily["precipitation_probability_max"][0]
    wind = daily["wind_speed_10m_max"][0]

    return (
        f"**天气：** {weather}\n"
        f"**气温：** {t_min}℃ ~ {t_max}℃\n"
        f"**降水概率：** {rain}%\n"
        f"**最大风速：** {wind} km/h\n"
    )


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


def build_message():
    now = datetime.now(TZ)

    lines = [
        "# 每日资讯早报",
        f"> {now.strftime('%Y年%m月%d日')} 星期"
        f"{'一二三四五六日'[now.weekday()]}",
        "",
        "## 一、今日天气 | 西安",
    ]

    try:
        lines.append(get_weather())
    except Exception as e:
        print("天气获取失败：", e)
        lines.append("天气数据暂时无法获取。\n")

    section_names = [
        "国内新闻",
        "国际新闻",
        "科技资讯",
        "财经新闻",
        "AI行业动态",
    ]

    for index, name in enumerate(section_names, start=2):
        lines.append(f"## {index}、{name}")

        try:
            news_list = get_news(NEWS_CATEGORIES[name])

            if not news_list:
                lines.append("暂无符合条件的新闻。\n")
                continue

            for i, news in enumerate(news_list, start=1):
                lines.append(
                    f"{i}. [{news['title']}]({news['link']})\n"
                    # f"   > 来源：{news['source']}"
                )

            lines.append("")

        except Exception as e:
            print(f"{name} 获取失败：", e)
            lines.append("本栏目暂时无法获取。\n")

    lines.extend([
        "---",
        "> 数据来源：Open-Meteo、Google News RSS",
    ])

    return "\n".join(lines)



def send_wecom(message):
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
        "topic_code": topic_code
    }

    request = urllib.request.Request(
        "https://api.wpush.cn/api/v1/send",
        data=urllib.parse.urlencode(data).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise RuntimeError(
            f"WPush HTTP错误：{error.code}，{detail}"
        )

    if result.get("code") != 0:
        raise RuntimeError(f"WPush发送失败：{result}")

    print(f"WPush消息提交成功，消息ID：{result.get('data')}")

if __name__ == "__main__":
    message = build_message()
    print(message)
    send_wecom(message)
