import os
import yfinance as yf
from supabase import create_client
from datetime import datetime, timedelta
import time
import json

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TABLE_NAME = "path_occurrences"

# 资产名称到 yfinance ticker 的映射
ASSET_TO_TICKER = {
    "NVDA": "NVDA", "NVIDIA": "NVDA",
    "AAPL": "AAPL", "Apple": "AAPL",
    "MSFT": "MSFT", "Microsoft": "MSFT",
    "AMZN": "AMZN", "Amazon": "AMZN",
    "GOOGL": "GOOGL", "GOOG": "GOOGL", "Google": "GOOGL",
    "TSLA": "TSLA", "Tesla": "TSLA",
    "META": "META", "Meta": "META", "Facebook": "META",
    "NFLX": "NFLX", "Netflix": "NFLX",
    "AMD": "AMD",
    "INTC": "INTC", "Intel": "INTC",
    "IBM": "IBM",
    "ORCL": "ORCL", "Oracle": "ORCL",
    "CRM": "CRM", "Salesforce": "CRM",
    "ADBE": "ADBE", "Adobe": "ADBE",
    "PYPL": "PYPL", "PayPal": "PYPL",
    "QCOM": "QCOM", "Qualcomm": "QCOM",
    "TXN": "TXN", "Texas Instruments": "TXN",
    "AVGO": "AVGO", "Broadcom": "AVGO",
    "SPX": "^GSPC", "S&P 500": "^GSPC",
    "IXIC": "^IXIC", "Nasdaq": "^IXIC", "NASDAQ": "^IXIC",
    "DJI": "^DJI", "Dow": "^DJI",
    "GC": "GC=F", "Gold": "GC=F",
    "CL": "CL=F", "Oil": "CL=F", "WTI": "CL=F",
    "BTC": "BTC-USD", "Bitcoin": "BTC-USD",
    "ETH": "ETH-USD", "Ethereum": "ETH-USD",
}

def get_ticker_from_entity(entity):
    """从 trigger_entity 提取 ticker"""
    if not entity:
        return None
    # 直接匹配映射表
    if entity in ASSET_TO_TICKER:
        return ASSET_TO_TICKER[entity]
    # 尝试从文本中提取
    for name, ticker in ASSET_TO_TICKER.items():
        if name in entity:
            return ticker
    return None

def get_price_change(ticker, event_date, days=5):
    try:
        if isinstance(event_date, str):
            start = datetime.strptime(event_date, "%Y-%m-%d")
        else:
            start = event_date
        end = start + timedelta(days=days + 1)
        stock = yf.Ticker(ticker)
        hist = stock.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if hist.empty or len(hist) < 2:
            return None
        open_price = hist["Open"].iloc[0]
        close_price = hist["Close"].iloc[-1]
        return (close_price - open_price) / open_price * 100
    except Exception as e:
        print(f"⚠️ yfinance 获取 {ticker} 失败: {e}")
        return None

def main():
    print(f"🔄 回测开始: {datetime.now().isoformat()}")

    # 查询待回测的记录
    response = supabase.table(TABLE_NAME)\
        .select("*")\
        .eq("verification_status", "pending")\
        .limit(100)\
        .execute()

    records = response.data
    if not records:
        print("✅ 没有待回测的记录")
        return

    print(f"📊 找到 {len(records)} 条待回测记录")

    success_count = 0
    failed_count = 0

    for rec in records:
        rec_id = rec["id"]
        final_impact = rec.get("final_impact", {})
        predicted_dir = final_impact.get("direction", "")
        entity = rec.get("trigger_entity", "")
        event_date = rec.get("trigger_event_date")

        if not event_date or not predicted_dir or not entity:
            supabase.table(TABLE_NAME).update({
                "verification_status": "failed",
                "verified_at": datetime.now().isoformat()
            }).eq("id", rec_id).execute()
            failed_count += 1
            print(f"❌ 缺少字段: id={rec_id}")
            continue

        ticker = get_ticker_from_entity(entity)
        if not ticker:
            supabase.table(TABLE_NAME).update({
                "verification_status": "failed",
                "verified_at": datetime.now().isoformat()
            }).eq("id", rec_id).execute()
            failed_count += 1
            print(f"❌ 无法识别资产: {entity}")
            continue

        change = get_price_change(ticker, event_date, days=5)
        if change is None:
            supabase.table(TABLE_NAME).update({
                "verification_status": "failed",
                "verified_at": datetime.now().isoformat()
            }).eq("id", rec_id).execute()
            failed_count += 1
            print(f"❌ 无法获取 {ticker} 数据")
            continue

        if change > 0.5:
            actual_dir = "up"
        elif change < -0.5:
            actual_dir = "down"
        else:
            actual_dir = "neutral"

        is_correct = predicted_dir == actual_dir

        supabase.table(TABLE_NAME).update({
            "verification_status": "verified" if is_correct else "failed",
            "verified_at": datetime.now().isoformat(),
            "actual_outcome": {
                "direction": actual_dir,
                "change_percent": round(change, 2),
                "ticker": ticker
            }
        }).eq("id", rec_id).execute()

        status = "✅" if is_correct else "❌"
        print(f"{status} {entity}({ticker}) 预测:{predicted_dir} 实际:{actual_dir} ({change:+.1f}%)")
        success_count += 1
        time.sleep(0.5)

    print(f"🎉 回测完成: 成功 {success_count} 条, 失败 {failed_count} 条")

if __name__ == "__main__":
    main()
