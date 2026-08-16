import os
import yfinance as yf
from supabase import create_client
from datetime import datetime, timedelta
import time
from collections import Counter

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TABLE_NAME = "path_occurrences"

# ========== 完整的资产映射表 ==========
ASSET_TO_TICKER = {
    # ---- 科技股 ----
    "NVDA": "NVDA", "NVIDIA": "NVDA", "NVIDIA Corporation": "NVDA",
    "AAPL": "AAPL", "Apple": "AAPL", "Apple Inc.": "AAPL",
    "MSFT": "MSFT", "Microsoft": "MSFT", "Microsoft Corp": "MSFT",
    "AMZN": "AMZN", "Amazon": "AMZN", "Amazon.com Inc.": "AMZN",
    "GOOGL": "GOOGL", "GOOG": "GOOGL", "Google": "GOOGL", "Alphabet": "GOOGL",
    "META": "META", "Meta": "META", "Facebook": "META",
    "NFLX": "NFLX", "Netflix": "NFLX",
    "AMD": "AMD", "Advanced Micro Devices": "AMD",
    "INTC": "INTC", "Intel": "INTC",
    "QCOM": "QCOM", "Qualcomm": "QCOM",
    "TXN": "TXN", "Texas Instruments": "TXN",
    "MU": "MU", "Micron": "MU",
    "ARM": "ARM", "Arm Holdings": "ARM",
    "ORCL": "ORCL", "Oracle": "ORCL",
    "CRM": "CRM", "Salesforce": "CRM",
    "ADBE": "ADBE", "Adobe": "ADBE",
    "PYPL": "PYPL", "PayPal": "PYPL",
    "IBM": "IBM",
    "CSCO": "CSCO", "Cisco": "CSCO",
    "AVGO": "AVGO", "Broadcom": "AVGO",
    
    # ---- 金融股 ----
    "JPM": "JPM", "JPMorgan": "JPM", "JPMorgan Chase": "JPM",
    "BAC": "BAC", "Bank of America": "BAC",
    "WFC": "WFC", "Wells Fargo": "WFC",
    "GS": "GS", "Goldman Sachs": "GS",
    "MS": "MS", "Morgan Stanley": "MS",
    "C": "C", "Citigroup": "C",
    "V": "V", "Visa": "V",
    "MA": "MA", "Mastercard": "MA",
    
    # ---- 能源 ----
    "XOM": "XOM", "Exxon": "XOM", "ExxonMobil": "XOM",
    "CVX": "CVX", "Chevron": "CVX",
    "Oil": "CL=F", "WTI": "CL=F", "Crude": "CL=F",
    "CL": "CL=F",
    "Gasoline": "UGA",
    
    # ---- 消费 ----
    "KO": "KO", "Coca-Cola": "KO",
    "PEP": "PEP", "Pepsi": "PEP",
    "MCD": "MCD", "McDonald's": "MCD",
    "NKE": "NKE", "Nike": "NKE",
    "SBUX": "SBUX", "Starbucks": "SBUX",
    "DIS": "DIS", "Disney": "DIS",
    "T": "T", "AT&T": "T",
    "VZ": "VZ", "Verizon": "VZ",
    "TMUS": "TMUS", "T-Mobile": "TMUS",
    "UBER": "UBER",
    "LYFT": "LYFT",
    "ABNB": "ABNB", "Airbnb": "ABNB",
    "EBAY": "EBAY",
    "SHOP": "SHOP", "Shopify": "SHOP",
    "RNG": "RNG", "RingCentral": "RNG",
    "CHTR": "CHTR", "Charter": "CHTR",
    "DKS": "DKS", "Dick's": "DKS",
    "PARA": "PARA", "Paramount": "PARA",
    "WRLD": "WRLD",
    "BC": "BC", "Brunswick": "BC",
    "CFR": "CFR",
    "EME": "EME", "EMCOR": "EME",
    "CALM": "CALM", "Cal-Maine": "CALM",
    
    # ---- ETF / 指数 ----
    "SPY": "SPY",
    "S&P 500": "SPY",
    "SP500": "SPY",
    "SPX": "^GSPC",
    "VTSAX": "VTI",
    "DGRW": "DGRW",
    "URA": "URA",
    "URA": "URA",
    "IWM": "IWM",  # 小盘股
    "XLK": "XLK",  # 科技板块
    "XLF": "XLF",  # 金融板块
    "XLE": "XLE",  # 能源板块
    "XLV": "XLV",  # 医疗板块
    "XLI": "XLI",  # 工业板块
    "XRT": "XRT",  # 零售板块
    "XLP": "XLP",  # 消费必需品
    "XLU": "XLU",  # 公用事业
    "VNQ": "VNQ",  # 房地产
    "GDX": "GDX",  # 金矿
    "ITA": "ITA",  # 航空航天与国防
    "DRIV": "DRIV",  # 电动汽车
    "ICLN": "ICLN",  # 清洁能源
    "DBC": "DBC",  # 商品
    "EEM": "EEM",  # 新兴市场
    "EFA": "EFA",  # 发达国家
    "TLT": "TLT",  # 长期国债
    "SHY": "SHY",  # 短期国债
    "LQD": "LQD",  # 公司债
    "AGG": "AGG",  # 综合债券
    "AIQ": "AIQ",  # AI ETF
    "SOXX": "SOXX",  # 半导体
    "IBB": "IBB",  # 生物科技
    "VUG": "VUG",  # 成长股
    "VTV": "VTV",  # 价值股
    "VYM": "VYM",  # 高股息
    "MGC": "MGC",  # 大盘股
    "IPO": "IPO",  # 新股
    "MAGA": "MAGA",  # 特朗普相关
    "REZ": "REZ",  # 房地产
    "SPCE": "SPCE",  # 维珍银河（太空概念替代）
    "UFO": "UFO",  # 太空探索 ETF
    
    # ---- 加密货币 ----
    "BTC": "BTC-USD", "Bitcoin": "BTC-USD",
    "ETH": "ETH-USD", "Ethereum": "ETH-USD",
    
    # ---- 商品 ----
    "Gold": "GC=F",
    "GC": "GC=F",
    
    # ---- 外汇 ----
    "USD": "UUP",
    "GBP": "FXB",
    "INR": "INR=X",
    "AUD": "FXA",
    
    # ---- 指数 ----
    "Nasdaq": "^IXIC", "IXIC": "^IXIC",
    "Dow": "^DJI", "DJI": "^DJI",
    "Nifty": "^NSEI", "NSEI": "^NSEI",
    "IDX": "^JKSE",
    
    # ---- 无法识别的将返回 None ----
    # 对于无法映射的，脚本将跳过并标记为 failed
}

def get_ticker_from_entity(entity):
    """从 trigger_entity 提取 ticker（精确匹配 + 部分匹配）"""
    if not entity:
        return None
    
    # 1. 精确匹配
    if entity in ASSET_TO_TICKER:
        return ASSET_TO_TICKER[entity]
    
    # 2. 部分匹配（忽略大小写）
    entity_lower = entity.lower()
    for name, ticker in ASSET_TO_TICKER.items():
        if name.lower() in entity_lower:
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
        return None

def main():
    print(f"🔄 回测开始: {datetime.now().isoformat()}")

    # 查询待回测记录
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
    failed_entities = []

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
            failed_entities.append(entity or "MISSING")
            print(f"❌ 缺少字段: id={rec_id}")
            continue

        ticker = get_ticker_from_entity(entity)
        if not ticker:
            supabase.table(TABLE_NAME).update({
                "verification_status": "failed",
                "verified_at": datetime.now().isoformat()
            }).eq("id", rec_id).execute()
            failed_count += 1
            failed_entities.append(entity)
            print(f"❌ 无法识别资产: {entity}")
            continue

        change = get_price_change(ticker, event_date, days=5)
        if change is None:
            supabase.table(TABLE_NAME).update({
                "verification_status": "failed",
                "verified_at": datetime.now().isoformat()
            }).eq("id", rec_id).execute()
            failed_count += 1
            failed_entities.append(entity)
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

    # 输出无法识别的资产统计
    print("\n📋 无法识别的资产 TOP 10:")
    for entity, count in Counter(failed_entities).most_common(10):
        print(f"  {entity}: {count} 次")

    print(f"\n🎉 回测完成: 成功 {success_count} 条, 失败 {failed_count} 条")

if __name__ == "__main__":
    main()
