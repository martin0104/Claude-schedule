#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
台股突破選股器 - V3 (優化版)
篩選條件:
1. 當天成交量 > 昨天
2. 成交量 >= 8000 張
3. 準備挑戰新高（收盤價 >= 近20日最高價 * 0.95）
4. 近5日成交均量 > 前5日成交均量
"""

import logging
import statistics
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# HTTP Session (共用、帶 retry)
# ─────────────────────────────────────────────
def build_session(retries: int = 3, backoff: float = 0.5) -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    return session


SESSION = build_session()

INDUSTRY_CODE_MAP = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "07": "化學生技醫療", "08": "玻璃陶瓷",
    "09": "造紙工業", "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業",
    "14": "建材營造", "15": "航運業", "16": "觀光餐旅", "17": "金融保險",
    "18": "貿易百貨", "19": "綜合", "20": "其他",
    "21": "化學工業", "22": "生技醫療業", "23": "油電燃氣業", "24": "半導體業",
    "25": "電腦及週邊設備業", "26": "光電業", "27": "通信網路業",
    "28": "電子零組件業", "29": "電子通路業", "30": "資訊服務業",
    "31": "其他電子業", "80": "管理股票", "9299": "存託憑證",
}

INDUSTRY_EMOJI = {
    "水泥工業": "🏗️", "食品工業": "🍜", "塑膠工業": "🧪", "紡織纖維": "🧵",
    "電機機械": "⚙️", "電器電纜": "🔌", "化學工業": "🧪", "生技醫療業": "💊",
    "化學生技醫療": "💊", "玻璃陶瓷": "🏺", "造紙工業": "📰", "鋼鐵工業": "🔩",
    "橡膠工業": "🔧", "汽車工業": "🚗", "電子工業": "💻", "半導體業": "💻",
    "電腦及週邊設備業": "💻", "光電業": "💡", "通信網路業": "📡",
    "電子零組件業": "💻", "電子通路業": "💻", "資訊服務業": "💻",
    "其他電子業": "💻", "建材營造業": "🏗️", "建材營造": "🏗️",
    "航運業": "🚢", "觀光餐旅": "🏨",
    "金融保險業": "🏦", "金融保險": "🏦", "金融業": "🏦",
    "貿易百貨業": "🛒", "貿易百貨": "🛒", "油電燃氣業": "⛽",
    "綜合": "📊", "其他業": "📊", "其他": "📊",
    "存託憑證": "📜", "電子類": "💻", "數位雲端": "☁️",
}


# ─────────────────────────────────────────────
# StockInfo
# ─────────────────────────────────────────────
class StockInfo:
    __slots__ = ("code", "name", "market", "industry")

    def __init__(self, code: str, name: str, market: str, industry: str = "其他"):
        self.code = code
        self.name = name
        self.market = market
        self.industry = industry

    def __repr__(self):
        return f"StockInfo({self.code} {self.name} {self.market} {self.industry})"


# ─────────────────────────────────────────────
# 股票清單取得
# ─────────────────────────────────────────────
def fetch_twse_stocks() -> list[StockInfo]:
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        log.info("正在從證交所取得上市股票清單...")
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        stocks = []
        for item in data:
            code = item.get("Code", "").strip()
            name = item.get("Name", "").strip()
            if code.isdigit() and len(code) == 4:
                stocks.append(StockInfo(code=code, name=name or code, market="上市"))
        log.info("✅ 取得 %d 檔上市股票", len(stocks))
        return stocks
    except Exception as e:
        log.error("❌ 證交所 API 錯誤: %s", e)
        return []


def fetch_otc_stocks() -> list[StockInfo]:
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    try:
        log.info("正在從櫃買中心取得上櫃股票清單...")
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        stocks = []
        for item in data:
            code = item.get("SecuritiesCompanyCode", "").strip()
            name = item.get("CompanyName", "").strip()
            if code.isdigit() and len(code) == 4:
                stocks.append(StockInfo(code=code, name=name or code, market="上櫃"))
        log.info("✅ 取得 %d 檔上櫃股票", len(stocks))
        return stocks
    except Exception as e:
        log.error("❌ 櫃買中心 API 錯誤: %s", e)
        return []


def fetch_twse_industry_map() -> dict[str, str]:
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        mapping = {}
        for item in data:
            code = item.get("公司代號", "").strip()
            industry = item.get("產業別", "").strip()
            if code:
                mapping[code] = industry
        log.info("✅ 取得 %d 筆產業分類資料", len(mapping))
        return mapping
    except Exception as e:
        log.warning("⚠️ 無法取得產業分類: %s，將使用預設分類", e)
        return {}


def fetch_all_stocks() -> list[StockInfo]:
    twse = fetch_twse_stocks()
    otc = fetch_otc_stocks()
    industry_map = fetch_twse_industry_map()
    for s in twse:
        s.industry = industry_map.get(s.code, "其他")
    all_stocks = twse + otc
    log.info("📊 總計: %d 檔 (上市 %d + 上櫃 %d)", len(all_stocks), len(twse), len(otc))
    return all_stocks


# ─────────────────────────────────────────────
# 產業輔助
# ─────────────────────────────────────────────
def normalize_industry(industry: str) -> str:
    if industry in INDUSTRY_CODE_MAP:
        return INDUSTRY_CODE_MAP[industry]
    return industry if industry else "其他"


def get_industry_emoji(industry: str) -> str:
    normalized = normalize_industry(industry)
    return INDUSTRY_EMOJI.get(normalized, "📊")


# ─────────────────────────────────────────────
# Yahoo Finance 歷史資料
# ─────────────────────────────────────────────
def fetch_yahoo_history(stock: StockInfo, days: int = 35) -> dict | None:
    suffix = ".TW" if stock.market == "上市" else ".TWO"
    tw_symbol = f"{stock.code}{suffix}"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{tw_symbol}"
    params = {"interval": "1d", "range": f"{days}d"}

    try:
        resp = SESSION.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        result = data.get("chart", {}).get("result")
        if not result:
            return None

        result = result[0]
        timestamps = result.get("timestamp")
        quote = result.get("indicators", {}).get("quote", [{}])[0]

        if not timestamps or len(timestamps) < 25:
            return None

        opens = quote.get("open", [])
        closes = quote.get("close", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        volumes = quote.get("volume", [])

        history = []
        for i in range(len(timestamps)):
            o, c, h, lo, v = opens[i], closes[i], highs[i], lows[i], volumes[i]
            if c is not None and v is not None and v > 0 and o is not None:
                history.append({
                    "date": datetime.fromtimestamp(timestamps[i]),
                    "open": float(o),
                    "close": float(c),
                    "high": float(h) if h else float(c),
                    "low": float(lo) if lo else float(c),
                    "volume": int(v / 1000),
                })

        if len(history) < 25:
            return None

        return {"stock": stock, "history": history}

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            log.warning("⚠️ %s 被 rate limit，稍後重試", stock.code)
            time.sleep(2)
        return None
    except Exception as e:
        log.debug("%s 取得資料失敗: %s", stock.code, e)
        return None


# ─────────────────────────────────────────────
# 突破條件檢查
# ─────────────────────────────────────────────
def check_breakout(data: dict) -> dict | None:
    stock: StockInfo = data["stock"]
    history = data["history"]

    if len(history) < 25:
        return None

    latest = history[-1]
    prev = history[-2]

    if latest["volume"] <= prev["volume"]:
        return None
    if latest["volume"] < 8000:
        return None

    recent_20 = history[-20:]
    high_20d = max(h["high"] for h in recent_20)
    if latest["close"] < high_20d * 0.95:
        return None

    if len(history) < 10:
        return None

    avg_recent_5 = statistics.mean(h["volume"] for h in history[-5:])
    avg_prev_5 = statistics.mean(h["volume"] for h in history[-10:-5])

    if avg_prev_5 == 0 or avg_recent_5 <= avg_prev_5:
        return None

    volume_ratio = latest["volume"] / prev["volume"] if prev["volume"] > 0 else 0
    distance_pct = ((latest["close"] - high_20d) / high_20d) * 100
    vol_growth_pct = ((avg_recent_5 - avg_prev_5) / avg_prev_5) * 100

    o = latest["open"]
    h = latest["high"]
    l = latest["low"]
    c = latest["close"]

    body_top = max(o, c)
    body_bottom = min(o, c)
    upper_shadow = h - body_top
    lower_shadow = body_bottom - l
    body = abs(c - o)
    total_range = h - l

    upper_pct = (upper_shadow / total_range * 100) if total_range > 0 else 0
    lower_pct = (lower_shadow / total_range * 100) if total_range > 0 else 0
    body_pct = (body / total_range * 100) if total_range > 0 else 0
    is_doji = body_pct <= 20

    return {
        "code": stock.code,
        "name": stock.name,
        "market": stock.market,
        "industry": stock.industry,
        "price": latest["close"],
        "volume": latest["volume"],
        "prev_volume": prev["volume"],
        "volume_ratio": volume_ratio,
        "high_20d": high_20d,
        "distance_to_high": distance_pct,
        "avg_vol_recent": avg_recent_5,
        "avg_vol_prev": avg_prev_5,
        "vol_growth": vol_growth_pct,
        "upper_shadow_pct": upper_pct,
        "lower_shadow_pct": lower_pct,
        "body_pct": body_pct,
        "has_upper": upper_shadow > 0,
        "has_lower": lower_shadow > 0,
        "is_doji": is_doji,
    }


# ─────────────────────────────────────────────
# 並行掃描
# ─────────────────────────────────────────────
def scan_stocks(
    stock_list: list[StockInfo],
    max_workers: int = 15,
    min_delay: float = 0.02,
) -> list[dict]:
    matched: list[dict] = []
    failed = 0
    processed = 0
    lock = Lock()
    start_time = time.time()
    total = len(stock_list)

    log.info("開始掃描 %d 檔股票 (workers=%d)...", total, max_workers)

    def _process(stock: StockInfo) -> dict | None:
        nonlocal failed, processed
        time.sleep(min_delay)

        data = fetch_yahoo_history(stock)
        if data is None:
            with lock:
                failed += 1
            return None

        result = check_breakout(data)

        with lock:
            processed += 1
            if processed % 100 == 0:
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = (total - processed) / rate if rate > 0 else 0
                log.info(
                    "進度: %d/%d (%d%%) | 符合: %d | 失敗: %d | 速度: %.1f檔/秒 | 剩餘: %.1f分鐘",
                    processed, total, processed * 100 // total,
                    len(matched), failed, rate, remaining / 60,
                )

        return result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process, s): s for s in stock_list}
        for future in as_completed(futures):
            stock = futures[future]
            try:
                result = future.result()
                if result:
                    with lock:
                        matched.append(result)
                    log.info(
                        "✅ %s %s (%s) $%.2f 量:%d張",
                        result["code"], result["name"], result["market"],
                        result["price"], result["volume"],
                    )
            except Exception as e:
                log.error("❌ %s 處理失敗: %s", stock.code, e)

    elapsed = time.time() - start_time
    log.info(
        "掃描完成！符合: %d | 失敗: %d | 總耗時: %.1f 分鐘",
        len(matched), failed, elapsed / 60,
    )
    return matched


# ─────────────────────────────────────────────
# 報告產生
# ─────────────────────────────────────────────
def format_report(matched: list[dict]) -> str:
    now = datetime.now()
    lines: list[str] = []
    lines.append("🚀 台股突破選股報告")
    lines.append(f"🕒 {now.strftime('%Y/%m/%d %H:%M')}")
    lines.append(f"✅ 符合條件: {len(matched)} 檔")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("📋 篩選條件:")
    lines.append("1️⃣ 當天成交量 > 昨天")
    lines.append("2️⃣ 成交量 >= 8,000 張")
    lines.append("3️⃣ 準備挑戰新高 (距20日高點 < 5%)")
    lines.append("4️⃣ 近5日均量 > 前5日均量")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("")

    if not matched:
        lines.append("今日無符合條件的股票")
        lines.append("")
        lines.append("⚠️ 僅供參考，不構成投資建議")
        return "\n".join(lines)

    matched.sort(key=lambda x: x["volume"], reverse=True)
    lines.append("🔥 符合標的（依成交量排序）:")
    lines.append("")

    for i, s in enumerate(matched, 1):
        industry_name = normalize_industry(s["industry"])
        emoji = get_industry_emoji(s["industry"])
        doji_mark = " ⭐十字星" if s.get("is_doji", False) else ""

        lines.append(f"{i}. {s['code']} {s['name']}{doji_mark} ({s['market']}) {emoji}{industry_name}")
        lines.append(f"   💰 ${s['price']:.2f} | 📊 {s['volume']:,}張 | 📈 量比 {s['volume_ratio']:.2f}x")

        upper = s.get("upper_shadow_pct", 0)
        lower = s.get("lower_shadow_pct", 0)
        if upper > 0 or lower > 0:
            lines.append(f"   🕯️ 上影 {upper:.1f}% | 下影 {lower:.1f}%")

        if s["distance_to_high"] >= 0:
            lines.append(f"   🎯 創20日新高 | 🔥 近5日均量成長 {s['vol_growth']:.0f}%")
        else:
            lines.append(f"   🎯 距高點 {s['distance_to_high']:.1f}% | 🔥 近5日均量成長 {s['vol_growth']:.0f}%")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("💡 觀察重點:")
    lines.append("")

    industry_count: dict[str, int] = {}
    for s in matched:
        ind = normalize_industry(s["industry"])
        industry_count[ind] = industry_count.get(ind, 0) + 1

    if industry_count:
        top_ind = sorted(industry_count.items(), key=lambda x: x[1], reverse=True)[:3]
        for ind_name, cnt in top_ind:
            if cnt >= 2:
                lines.append(f"• {ind_name}表現強勢（{cnt} 檔入榜）")

    new_high_count = sum(1 for s in matched if s["distance_to_high"] >= 0)
    if new_high_count > 0:
        lines.append(f"• {new_high_count} 檔創 20 日新高，動能強勁")

    doji_count = sum(1 for s in matched if s.get("is_doji", False))
    if doji_count > 0:
        lines.append(f"• {doji_count} 檔呈十字星型態（多空膠著）")

    avg_growth = statistics.mean(s["vol_growth"] for s in matched)
    lines.append(f"• 近5日均量平均成長 {avg_growth:.0f}%")

    lines.append("")
    lines.append("⚠️ 僅供參考，不構成投資建議")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 主程式入口（供直接執行）
# ─────────────────────────────────────────────
def run_and_get_report(max_workers: int = 15) -> str:
    """執行選股並回傳報告字串（供 scheduler 呼叫）"""
    stock_list = fetch_all_stocks()
    if not stock_list:
        return "❌ 無法取得股票清單，請檢查網路連線。"
    matched = scan_stocks(stock_list, max_workers=max_workers)
    return format_report(matched)


if __name__ == "__main__":
    import os

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("請設定 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID")

    def send_telegram(message: str):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        TG_MAX_LEN = 4096
        chunks = [message[i:i + TG_MAX_LEN] for i in range(0, len(message), TG_MAX_LEN)]
        for chunk in chunks:
            try:
                resp = requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=10)
                resp.raise_for_status()
            except requests.RequestException as e:
                log.error("Telegram 發送失敗: %s", e)

    send_telegram("⏳ 台股選股開始執行，請稍候...")

    try:
        report = run_and_get_report(max_workers=15)
        send_telegram(report)
    except Exception as e:
        send_telegram(f"❌ 選股執行失敗: {e}")
