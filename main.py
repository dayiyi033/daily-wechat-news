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

# 国内新闻优先，国际新闻只保留重大事件；多主题搜索避免单一查询漏新闻。
DOMESTIC_NEWS_LIMIT = 6
INTERNATIONAL_NEWS_LIMIT = 3

DOMESTIC_NEWS_QUERIES = [
    "中国 重要政策 政策发布 国务院 部委",
    "中国 经济 财政 货币 房地产 就业 消费",
    "中国 社会 民生 教育 医疗 交通 公共安全",
    "中国 科技 产业 制造业 能源 重大进展",
    "中国 新闻 今日",
]

INTERNATIONAL_NEWS_QUERIES = [
    "国际 战争 冲突 停火 制裁 地缘政治",
    "国际 全球经济 美联储 央行 贸易 关税",
    "国际 灾害 地震 疫情 公共安全",
    "国际 科技 芯片 人工智能 重大突破",
    "国际 新闻 今日",
]

# 关键词按重要程度加权。分值越高，越优先；同一关键词组命中多项可累加。
DOMESTIC_KEYWORD_WEIGHTS = {
    "高": (8, (
        "中央政治局", "中央经济工作会议", "全国两会", "政府工作报告",
        "国务院常务会议", "重大政策", "重要政策", "国家战略", "法律通过",
        "法律实施", "重大改革", "重大部署", "国家统计局", "国民经济",
        "重大事故", "重大灾害", "重大安全事故", "公共卫生事件",
        "全国性", "全国范围", "央行降准", "央行降息", "金融监管",
    )),
    "中": (5, (
        "政策出台", "政策调整", "新规", "条例", "办法发布", "经济增长",
        "房地产", "房价", "就业", "失业率", "消费", "出口", "进口",
        "财政", "税收", "人民币", "股市", "能源", "粮食", "医疗",
        "医保", "教育", "高考", "养老金", "社保", "极端天气",
        "洪水", "台风", "地震", "火灾", "交通事故", "供应链",
        "芯片", "人工智能", "科技突破", "产业升级",
    )),
    "一般": (2, (
        "发布", "公布", "启动", "推进", "改革", "建设", "项目",
        "企业", "市场", "消费市场", "创新", "发展",
    )),
}

INTERNATIONAL_KEYWORD_WEIGHTS = {
    "高": (10, (
        "战争", "全面战争", "大规模冲突", "军事入侵", "停火协议",
        "和平协议", "政变", "核武器", "核试验", "核威胁", "重大制裁",
        "金融危机", "全球金融", "全球经济衰退", "全球疫情", "重大地震",
        "海啸", "重大恐袭", "恐怖袭击", "联合国安理会", "北约集体防御",
    )),
    "中": (6, (
        "美联储", "欧洲央行", "日本央行", "央行降息", "央行加息",
        "贸易战", "关税", "出口管制", "芯片禁令", "能源危机",
        "石油供应", "天然气供应", "总统选举", "大选结果", "国际峰会",
        "制裁", "入侵", "空袭", "导弹袭击", "军事冲突", "地缘政治",
        "重大灾害", "飓风", "台风", "疫情", "人工智能突破",
        "重大科技突破", "全球供应链",
    )),
    "低": (2, (
        "总统", "首相", "外交", "联合国", "欧盟", "北约", "中东",
        "俄乌", "巴以", "峰会", "国际贸易", "国际市场",
    )),
}

# 过滤明显低价值内容；不作为唯一筛选条件，避免误删重要新闻。
NEWS_EXCLUDE_KEYWORDS = (
    "明星八卦", "娱乐圈恋情", "综艺花絮", "网红带货", "彩票开奖",
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


def normalize_news_title(title):
    """清理标题格式，用于完全重复标题去重。"""
    import re
    value = (title or "").strip().lower()
    # Google News 标题常以“ - 媒体名”结尾。
    value = re.sub(r"\s+-\s+[^-]{2,40}$", "", value)
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)


# 仅用于事件相似度判断的主题泛词。APEC 等组织名不作为事件相同的依据。
NEWS_SIMILARITY_STOPWORDS = {
    "中国", "我国", "国内", "国际", "全球", "世界", "今日", "最新",
    "消息", "新闻", "报道", "表示", "指出", "认为", "有关", "相关",
    "情况", "影响", "背后", "观察", "关注", "分析", "解读", "如何",
    "什么", "一个", "多个", "持续", "进一步", "正式", "举行", "进行",
    "会议", "活动", "发展", "经济", "科技", "产业", "领域", "方面",
    "APEC", "亚太经合组织", "亚太经合", "峰会",
}

# 同义动作归为一类；不同类别通常代表不同事件，不自动合并。
NEWS_EVENT_ACTIONS = {
    "会议召开": ("开幕", "启幕", "召开", "举行", "举办"),
    "访问会晤": ("访问", "访华", "会见", "会晤", "会谈", "出访"),
    "政策发布": ("出台", "发布", "公布", "通过", "实施", "调整", "宣布"),
    "协议签署": ("签署", "签订", "达成协议", "达成共识"),
    "军事冲突": ("袭击", "空袭", "轰炸", "进攻", "入侵", "交火", "停火"),
    "事故灾害": ("地震", "洪水", "火灾", "爆炸", "坍塌", "事故"),
    "企业经营": ("收购", "并购", "裁员", "破产", "上市", "融资"),
}


def _news_action_group(title):
    hits = []
    for group, verbs in NEWS_EVENT_ACTIONS.items():
        for verb in verbs:
            if verb in title:
                hits.append((len(verb), group))
    return max(hits)[1] if hits else None


def _news_char_ngrams(title, n=2):
    """提取中文字符 n-gram；移除宽泛主题词，避免仅因同属 APEC 而相似。"""
    import re
    value = normalize_news_title(title)
    for word in sorted(NEWS_SIMILARITY_STOPWORDS, key=len, reverse=True):
        value = value.replace(word.lower(), "")
    value = re.sub(r"[0-9年月日时分]", "", value)
    if len(value) < n:
        return {value} if value else set()
    return {value[i:i+n] for i in range(len(value) - n + 1)}


def news_event_similarity(title_a, title_b):
    """返回保守的标题事件相似度；不把共同主题词直接视为同一事件。"""
    from difflib import SequenceMatcher

    a = normalize_news_title(title_a)
    b = normalize_news_title(title_b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    action_a = _news_action_group(title_a)
    action_b = _news_action_group(title_b)
    if action_a and action_b and action_a != action_b:
        return 0.0

    grams_a = _news_char_ngrams(title_a)
    grams_b = _news_char_ngrams(title_b)
    union = grams_a | grams_b
    jaccard = len(grams_a & grams_b) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, a, b).ratio()
    similarity = max(jaccard, sequence)

    # 中等相似度还必须有足够多的共同内容片段，降低同主题误删概率。
    shared_anchors = len(grams_a & grams_b)
    if similarity >= 0.86:
        return similarity
    if similarity >= 0.70 and shared_anchors >= 3:
        return similarity

    # 标题改写幅度较大时，仅在“事件动作类别相同 + 多个内容片段重合”时合并。
    # 例如“化工厂爆炸事故”与“化工厂爆炸造成多人伤亡”；没有共同动作类别则不走此分支。
    if action_a and action_a == action_b and similarity >= 0.50 and shared_anchors >= 6:
        return similarity
    return 0.0


def deduplicate_news_events(ranked_news):
    """事件级保守去重。输入应已按优先级排序，保留排序靠前的代表新闻。"""
    kept = []
    for item in ranked_news:
        duplicate_of = None
        for existing in kept:
            similarity = news_event_similarity(item["title"], existing["title"])
            if similarity:
                duplicate_of = existing
                break

        if duplicate_of is None:
            kept.append(item)
        else:
            print(
                "合并疑似重复新闻："
                f"[{item['title']}] -> [{duplicate_of['title']}]"
            )
    return kept


def get_news(query, max_items=30, max_age_hours=36):
    params = {
        "q": query + f" when:{max(1, int((max_age_hours + 23) // 24))}d",
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
    now = datetime.now(TZ)

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

        if not title or not link:
            continue

        # 有发布时间时严格过滤过旧或异常的未来新闻；缺少时间的条目保留，避免误清空。
        if pub_date:
            age_hours = (now - pub_date).total_seconds() / 3600
            if age_hours > max_age_hours or age_hours < -6:
                continue

        key = normalize_news_title(title)
        if not key or key in seen:
            continue

        seen.add(key)
        results.append({
            "title": title,
            "source": source,
            "link": link,
            "published": pub_date,
        })

        if len(results) >= max_items:
            break

    return results


def collect_news(queries, max_age_hours=36):
    """逐个主题抓取；单个查询失败不影响其他查询。"""
    merged = []
    seen = set()
    failures = 0

    for query in queries:
        try:
            batch = get_news(query, max_items=30, max_age_hours=max_age_hours)
            for item in batch:
                key = normalize_news_title(item["title"])
                if key and key not in seen:
                    seen.add(key)
                    merged.append(item)
        except Exception as error:
            failures += 1
            print(
                f"新闻子查询失败 [{query}]："
                f"{type(error).__name__}: {error}"
            )

    return merged, failures


def score_news(news, weights):
    title = news["title"]
    if any(word in title for word in NEWS_EXCLUDE_KEYWORDS):
        return 0, "过滤"

    score = 0
    priority = "一般"
    for level, (weight, keywords) in weights.items():
        hits = [word for word in keywords if word in title]
        if hits:
            # 每个优先级最多累计 2 个关键词，避免堆叠关键词造成分数失真。
            score += min(len(hits), 2) * weight
            if level == "高":
                priority = "高"
            elif level in ("中", "低") and priority != "高":
                priority = "中" if level == "中" else priority

    if score == 0:
        priority = "一般"
    return score, priority


def rank_news(news_list, weights):
    ranked = []
    for item in news_list:
        score, priority = score_news(item, weights)
        if priority == "过滤":
            continue
        item = dict(item)
        item["score"] = score
        item["priority"] = priority
        ranked.append(item)

    # 优先级分数优先，同分时优先发布时间较新的新闻。
    ranked.sort(
        key=lambda item: (
            item["score"],
            item["published"].timestamp() if item["published"] else 0,
        ),
        reverse=True,
    )

    # 排序后去重：同一事件优先保留关键词分数更高、发布时间更新的报道。
    return deduplicate_news_events(ranked)


def format_news_item(index, news, fallback=False):
    """新闻标题与来源、时间分行展示，保留原始链接。"""
    label = news.get("priority", "一般")
    if fallback:
        label = "兜底关注"

    published_text = (
        news["published"].strftime("%m-%d %H:%M")
        if news.get("published") else "发布时间未知"
    )

    return (
        f"**{index:02d}｜{label}**\n"
        f"[{news['title']}]({news['link']})\n"
        f"> 来源：{news['source']}　|　发布时间：{published_text}"
    )


def append_news_section(lines, title, queries, limit, international=False):
    lines.extend([f"### {title}", ""])

    # 第一轮：最近 36 小时，多主题搜索。
    news_list, failures = collect_news(queries, max_age_hours=36)

    # 如果结果太少，放宽到最近 48 小时并追加宽泛查询；不会用无日期旧缓存冒充新消息。
    if len(news_list) < limit:
        fallback_queries = (
            ["国际 新闻 全球 最新"] if international else ["中国 国内 新闻 最新"]
        )
        extra, extra_failures = collect_news(fallback_queries, max_age_hours=48)
        failures += extra_failures
        known = {normalize_news_title(item["title"]) for item in news_list}
        for item in extra:
            key = normalize_news_title(item["title"])
            if key and key not in known:
                known.add(key)
                news_list.append(item)

    if not news_list:
        if failures:
            lines.append("新闻接口暂时无法获取（多个 RSS 查询均失败），本次没有可核实的新闻内容。")
        else:
            lines.append("新闻源在最近 48 小时内未返回可用条目，未编造新闻。")
        lines.append("")
        return

    weights = INTERNATIONAL_KEYWORD_WEIGHTS if international else DOMESTIC_KEYWORD_WEIGHTS
    ranked = rank_news(news_list, weights)

    if international:
        # 国际新闻优先要求“高/中”级别；若没有命中，则从最新的可用国际新闻中补 1 条，明确标记兜底。
        major = [item for item in ranked if item["priority"] in ("高", "中")]
        if major:
            selected = major[:limit]
            fallback_ids = set()
        else:
            selected = ranked[:1]
            fallback_ids = {id(selected[0])} if selected else set()
    else:
        # 国内新闻按分数排序；即使没有命中高权重词，也从近期结果中选取，避免正常有源却空栏。
        selected = ranked[:limit]
        fallback_ids = set()
        if selected and all(item["score"] == 0 for item in selected):
            fallback_ids = {id(item) for item in selected}

    if not selected:
        # 最后兜底：如果仅因关键词排除规则导致为空，从原始新闻中选最新一条。
        selected = sorted(
            news_list,
            key=lambda item: item["published"].timestamp() if item["published"] else 0,
            reverse=True,
        )[:1]
        for item in selected:
            item["priority"] = "一般"
            item["score"] = 0
        fallback_ids = {id(item) for item in selected}

    for index, item in enumerate(selected, start=1):
        if index > 1:
            lines.append("")
        lines.append(format_news_item(index, item, fallback=id(item) in fallback_ids))

    if international and fallback_ids:
        lines.append("> 注：本次没有检索到达到重大事件关键词阈值的新闻，以上为近期国际动态兜底条目，不代表已判定为重大事件。")
    elif fallback_ids:
        lines.append("> 注：以上为关键词未命中高优先级词条时的近期新闻兜底结果。")

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

            lines.extend([
                f"**指数点位：{item['close']:,.2f} 点**",
                f"**涨跌幅：{item['change_pct']:+.2f}%**（较前一交易日）",
                f"> 交易日期：{item['trade_date']}（美东时间）",
            ])

            if item["market_update"]:
                lines.append(
                    f"> 行情更新时间：{item['market_update'].strftime('%Y-%m-%d %H:%M:%S')} "
                    "（北京时间，Yahoo Finance）"
                )
            else:
                lines.append(
                    f"> 数据抓取时间：{item['fetched_at'].strftime('%Y-%m-%d %H:%M:%S')} "
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
        f"**Au99.99：{latest['close']:.2f} 元/克**\n"
        f"**涨跌：** {change_text}\n"
        f"> 交易日期：{latest['date'].isoformat()}（上海黄金交易所）\n"
        f"> 抓取时间：{fetched_at.strftime('%Y-%m-%d %H:%M:%S')}（北京时间）\n"
        f"> 数据状态：{status}"
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
            f"　|　生成时间：{now.strftime('%H:%M:%S')}（北京时间）"
        ),
        "",
        "---",
        "## 01｜今日天气 · 西安",
        "",
    ]

    try:
        lines.append(get_weather())
    except Exception as error:
        print(
            f"天气获取失败："
            f"{type(error).__name__}: {error}"
        )
        lines.append("**天气数据暂时无法获取。**")

    lines.extend([
        "",
        "---",
        "## 02｜国内热点新闻",
        "",
        "> 按重要程度排序 · 最多 6 条",
        "",
    ])

    append_news_section(
        lines,
        "国内热点 · 重要资讯",
        DOMESTIC_NEWS_QUERIES,
        DOMESTIC_NEWS_LIMIT,
        international=False,
    )

    lines.extend([
        "",
        "---",
        "## 03｜国际重大新闻",
        "",
        "> 严格筛选重大事件 · 最多 3 条",
        "",
    ])

    append_news_section(
        lines,
        "国际热点 · 重大事件",
        INTERNATIONAL_NEWS_QUERIES,
        INTERNATIONAL_NEWS_LIMIT,
        international=True,
    )

    lines.extend([
        "",
        "---",
        "## 04｜财经行情",
        "",
        "### 纳斯达克100",
        "",
    ])

    lines.extend(get_us_market())

    lines.extend([
        "",
        "### 黄金 · Au99.99",
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
            "**Au99.99：暂时无法获取有效行情。**\n"
            "> 未使用旧数据冒充最新价格。"
        )

    lines.extend([
        "",
        "---",
        "**数据来源**",
        "> 天气：Open-Meteo　|　新闻：Google News RSS（多主题检索）",
        "> 美股：Yahoo Finance　|　黄金：上海黄金交易所",
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
