import os
import re
import json
import time
from collections import Counter
from datetime import datetime, timedelta

import yfinance as yf
from supabase import create_client

# ==================== 配置 ====================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")   # 建议使用 service_role key

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TABLE_NAME = "path_occurrences"

# ========== 完整的资产映射表（原样保留） ==========
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
    "IWM": "IWM",
    "XLK": "XLK",
    "XLF": "XLF",
    "XLE": "XLE",
    "XLV": "XLV",
    "XLI": "XLI",
    "XRT": "XRT",
    "XLP": "XLP",
    "XLU": "XLU",
    "VNQ": "VNQ",
    "GDX": "GDX",
    "ITA": "ITA",
    "DRIV": "DRIV",
    "ICLN": "ICLN",
    "DBC": "DBC",
    "EEM": "EEM",
    "EFA": "EFA",
    "TLT": "TLT",
    "SHY": "SHY",
    "LQD": "LQD",
    "AGG": "AGG",
    "AIQ": "AIQ",
    "SOXX": "SOXX",
    "IBB": "IBB",
    "VUG": "VUG",
    "VTV": "VTV",
    "VYM": "VYM",
    "MGC": "MGC",
    "IPO": "IPO",
    "MAGA": "MAGA",
    "REZ": "REZ",
    "SPCE": "SPCE",
    "UFO": "UFO",
    
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
}

# ==================== 因果路径相关函数 ====================

def extract_keywords(text):
    """
    从事件标题中提取英文金融关键词，用于匹配 causal_paths
    """
    if not text:
        return []
    # 只取英文字母（去掉数字和符号）
    words = re.findall(r'[a-zA-Z]+', text.lower())
    # 英文金融关键词白名单
    finance_keywords = [
        'rate', 'hike', 'cut', 'fed', 'fomc', 'interest', 'powell',
        'earnings', 'revenue', 'beat', 'miss', 'eps', 'profit',
        'cpi', 'inflation', 'pce', 'core', 'price',
        'jobs', 'unemployment', 'payroll', 'nonfarm',
        'geopolitical', 'conflict', 'war', 'oil', 'crude', 'gas',
        'macro', 'data', 'gdp', 'retail', 'sales'
    ]
    keywords = [w for w in words if w in finance_keywords]
    return list(set(keywords))


def get_or_create_path(keywords, trigger_title):
    """
    根据关键词匹配 causal_paths，如果无匹配则返回 UNKNOWN_GENERIC
    返回路径对象（包含 id）
    """
    # 1. 获取所有现有路径
    all_paths = supabase.table('causal_paths').select('*').execute().data
    
    # 2. 尝试匹配（至少一个关键词命中）
    for path in all_paths:
        path_keywords = path.get('trigger_keywords', [])
        if set(keywords) & set(path_keywords):
            return path
    
    # 3. 无匹配 → 使用 UNKNOWN_GENERIC（如果不存在则创建）
    unknown = next((p for p in all_paths if p['path_signature'] == 'UNKNOWN_GENERIC'), None)
    if not unknown:
        new_path = {
            'path_signature': 'UNKNOWN_GENERIC',
            'path_description': 'Uncategorized fallback path',
            'trigger_type': 'UNKNOWN',
            'trigger_keywords': []
        }
        resp = supabase.table('causal_paths').insert(new_path).execute()
        unknown = resp.data[0]
    return unknown


# ==================== 原有资产识别与价格获取函数 ====================

def get_ticker_from_entity(entity):
    """从 trigger_entity 提取 ticker（精确匹配 + 部分匹配）"""
    if not entity:
        return None
    
    if entity in ASSET_TO_TICKER:
        return ASSET_TO_TICKER[entity]
    
    entity_lower = entity.lower()
    for name, ticker in ASSET_TO_TICKER.items():
        if name.lower() in entity_lower:
            return ticker
    
    return None


def get_price_change(ticker, event_date, days=5):
    """
    获取事件发生后 days 个交易日内的涨跌幅（%）
    返回 float 或 None
    """
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


# ==================== 主回测逻辑 ====================

def main():
    print(f"🔄 回测开始: {datetime.now().isoformat()}")

    # 查询待回测记录（每次 100 条）
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

    # 统计分类
    correct_count = 0          # 预测正确
    wrong_count = 0            # 预测错误（有数据）
    deleted_no_ticker = 0      # 无法识别资产 → 删除
    deleted_no_data = 0        # 无数据 → 删除
    missing_fields = 0         # 缺少字段 → 删除

    for rec in records:
        rec_id = rec["id"]
        final_impact = rec.get("final_impact", {})
        # 如果 final_impact 是字符串，尝试解析 JSON
        if isinstance(final_impact, str):
            try:
                final_impact = json.loads(final_impact)
            except:
                final_impact = {}
        predicted_dir = final_impact.get("direction", "")
        entity = rec.get("trigger_entity", "")
        event_date = rec.get("trigger_event_date")
        trigger_title = rec.get("trigger_event_title", "")

        # ---- 1. 缺少必要字段 → 删除 ----
        if not event_date or not predicted_dir or not entity:
            supabase.table(TABLE_NAME).delete().eq("id", rec_id).execute()
            missing_fields += 1
            print(f"🗑️ 缺少字段，删除: id={rec_id}")
            continue

        # ---- 2. 无法识别资产 → 删除 ----
        ticker = get_ticker_from_entity(entity)
        if not ticker:
            supabase.table(TABLE_NAME).delete().eq("id", rec_id).execute()
            deleted_no_ticker += 1
            print(f"🗑️ 无法识别资产，删除: {entity}")
            continue

        # ---- 3. 获取实际价格 ----
        change = get_price_change(ticker, event_date, days=5)
        if change is None:
            supabase.table(TABLE_NAME).delete().eq("id", rec_id).execute()
            deleted_no_data += 1
            print(f"🗑️ 无数据，删除: {ticker} ({entity})")
            continue

        # ---- 4. 有数据 → 进行路径匹配与统计 ----
        # 提取关键词，匹配 causal_paths
        keywords = extract_keywords(trigger_title)
        path_obj = get_or_create_path(keywords, trigger_title)
        path_id = path_obj['id']

        # 判断实际方向
        if change > 0.5:
            actual_dir = "up"
        elif change < -0.5:
            actual_dir = "down"
        else:
            actual_dir = "neutral"

        is_correct = (predicted_dir == actual_dir)

        # ---- 5. 调用 RPC 更新路径统计 ----
        try:
            supabase.rpc('update_path_stats', {
                'p_path_id': path_id,
                'p_predicted_direction': predicted_dir,
                'p_actual_direction': actual_dir,
                'p_event_title': trigger_title,
                'p_ticker': ticker
            }).execute()
        except Exception as e:
            print(f"⚠️ 更新路径统计失败: {e}")

        # ---- 6. 更新原记录 ----
        supabase.table(TABLE_NAME).update({
            "verification_status": "verified" if is_correct else "failed",
            "verified_at": datetime.now().isoformat(),
            "actual_outcome": {
                "direction": actual_dir,
                "change_percent": round(change, 2),
                "ticker": ticker
            },
            "path_id": path_id
        }).eq("id", rec_id).execute()

        if is_correct:
            correct_count += 1
            print(f"✅ {entity}({ticker}) 预测:{predicted_dir} 实际:{actual_dir} ({change:+.1f}%)")
        else:
            wrong_count += 1
            print(f"❌ 预测错误 {entity}({ticker}) 预测:{predicted_dir} 实际:{actual_dir} ({change:+.1f}%)")

        time.sleep(0.5)

    # ---- 输出统计 ----
    total_processed = correct_count + wrong_count + deleted_no_ticker + deleted_no_data + missing_fields
    total_verifiable = correct_count + wrong_count

    print("\n" + "="*60)
    print("📊 回测统计报告")
    print("="*60)
    print(f"总处理: {total_processed} 条")
    print(f"  ✅ 预测正确: {correct_count} 条")
    print(f"  ❌ 预测错误: {wrong_count} 条")
    print(f"  🗑️ 删除（无法识别资产）: {deleted_no_ticker} 条")
    print(f"  🗑️ 删除（无数据）: {deleted_no_data} 条")
    print(f"  🗑️ 删除（缺少字段）: {missing_fields} 条")
    print("-"*60)
    
    if total_verifiable > 0:
        accuracy = correct_count / total_verifiable * 100
        print(f"📈 准确率（仅计算有数据可验证的）: {accuracy:.1f}% ({correct_count}/{total_verifiable})")
    else:
        print("📈 没有可验证的数据")
    
    print("="*60)
    print(f"\n🎉 回测完成")


if __name__ == "__main__":
    main()
