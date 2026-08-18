import os
import json
import time
from datetime import datetime, timedelta

import yfinance as yf
from supabase import create_client

# ==================== 配置 ====================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TABLE_NAME = "path_occurrences"

# ========== 资产映射表 ==========
ASSET_TO_TICKER = {
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
    "JPM": "JPM", "JPMorgan": "JPM", "JPMorgan Chase": "JPM",
    "BAC": "BAC", "Bank of America": "BAC",
    "WFC": "WFC", "Wells Fargo": "WFC",
    "GS": "GS", "Goldman Sachs": "GS",
    "MS": "MS", "Morgan Stanley": "MS",
    "C": "C", "Citigroup": "C",
    "V": "V", "Visa": "V",
    "MA": "MA", "Mastercard": "MA",
    "XOM": "XOM", "Exxon": "XOM", "ExxonMobil": "XOM",
    "CVX": "CVX", "Chevron": "CVX",
    "Oil": "CL=F", "WTI": "CL=F", "Crude": "CL=F", "CL": "CL=F",
    "SPY": "SPY", "S&P 500": "SPY", "SP500": "SPY", "SPX": "^GSPC",
    "BTC": "BTC-USD", "Bitcoin": "BTC-USD",
    "ETH": "ETH-USD", "Ethereum": "ETH-USD",
    "Gold": "GC=F", "GC": "GC=F",
    "USD": "UUP", "GBP": "FXB", "INR": "INR=X", "AUD": "FXA",
    "Nasdaq": "^IXIC", "IXIC": "^IXIC",
    "Dow": "^DJI", "DJI": "^DJI",
    "Nifty": "^NSEI", "NSEI": "^NSEI",
    "TLT": "TLT",
    "VYM": "VYM",
    "XLF": "XLF",
    "XLK": "XLK",
    "XLE": "XLE",
    "IWM": "IWM",
    "EEM": "EEM",
    "EFA": "EFA",
    "SOXX": "SOXX",
    "AIQ": "AIQ",
}


def get_ticker_from_entity(entity):
    """从 trigger_entity 提取 ticker"""
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
    获取事件发生后 days 个交易日的涨跌幅
    返回: (change_percent, actual_direction) 或 (None, None)
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
            return None, None
        open_price = hist["Open"].iloc[0]
        close_price = hist["Close"].iloc[-1]
        change = (close_price - open_price) / open_price * 100
        if change > 0.5:
            direction = "up"
        elif change < -0.5:
            direction = "down"
        else:
            direction = "neutral"
        return change, direction
    except Exception as e:
        return None, None


def main():
    print(f"🔄 回测开始: {datetime.now().isoformat()}")

    # ===== 只查询有 path_id 的 pending 记录（安全过滤） =====
    response = supabase.table(TABLE_NAME)\
        .select("*")\
        .eq("verification_status", "pending")\
        .not_.is_("path_id", "null")\
        .limit(100)\
        .execute()

    records = response.data
    if not records:
        print("✅ 没有待回测的记录（所有 pending 记录都有 path_id，或已处理完毕）")
        return

    print(f"📊 找到 {len(records)} 条待回测记录")

    # 统计
    stats = {
        "correct": 0,
        "wrong": 0,
        "no_ticker": 0,
        "no_data": 0,
        "bad_fields": 0,
        "db_error": 0
    }

    for rec in records:
        rec_id = rec["id"]
        path_id = rec.get("path_id")
        
        # 解析 final_impact
        final_impact = rec.get("final_impact", {})
        if isinstance(final_impact, str):
            try:
                final_impact = json.loads(final_impact)
            except:
                final_impact = {}
        
        predicted_dir = final_impact.get("direction", "")
        # 处理 up|down 多值
        if '|' in predicted_dir:
            predicted_dir = predicted_dir.split('|')[0]
        
        entity = rec.get("trigger_entity", "")
        event_date = rec.get("trigger_event_date")
        trigger_title = rec.get("trigger_event_title", "")

        # ---- 检查必要字段 ----
        if not event_date or not predicted_dir or not entity or not path_id:
            supabase.table(TABLE_NAME).delete().eq("id", rec_id).execute()
            stats["bad_fields"] += 1
            print(f"🗑️ 缺少字段，删除: id={rec_id}")
            continue

        # ---- 识别 ticker ----
        ticker = get_ticker_from_entity(entity)
        if not ticker:
            supabase.table(TABLE_NAME).delete().eq("id", rec_id).execute()
            stats["no_ticker"] += 1
            print(f"🗑️ 无法识别资产，删除: {entity}")
            continue

        # ---- 获取价格数据 ----
        change, actual_dir = get_price_change(ticker, event_date, days=5)
        if change is None:
            supabase.table(TABLE_NAME).delete().eq("id", rec_id).execute()
            stats["no_data"] += 1
            print(f"🗑️ 无数据，删除: {ticker} ({entity})")
            continue

        # ---- 判断是否正确 ----
        is_correct = (predicted_dir == actual_dir)

        # ---- 更新路径统计 ----
        try:
            supabase.rpc('update_path_stats', {
                'p_path_id': path_id,
                'p_predicted_direction': predicted_dir,
                'p_actual_direction': actual_dir,
                'p_event_title': trigger_title[:200],
                'p_ticker': ticker
            }).execute()
        except Exception as e:
            stats["db_error"] += 1
            print(f"⚠️ 更新路径统计失败: {e}")
            # 即使失败，也继续更新记录状态
            # 不跳过，让记录被标记

        # ---- 更新原记录 ----
        supabase.table(TABLE_NAME).update({
            "verification_status": "verified" if is_correct else "failed",
            "verified_at": datetime.now().isoformat(),
            "actual_outcome": {
                "direction": actual_dir,
                "change_percent": round(change, 2),
                "ticker": ticker
            }
        }).eq("id", rec_id).execute()

        if is_correct:
            stats["correct"] += 1
            print(f"✅ {entity}({ticker}) 预测:{predicted_dir} 实际:{actual_dir} ({change:+.1f}%)")
        else:
            stats["wrong"] += 1
            print(f"❌ 预测错误 {entity}({ticker}) 预测:{predicted_dir} 实际:{actual_dir} ({change:+.1f}%)")

        time.sleep(0.3)

    # ---- 统计报告 ----
    total_processed = sum(stats.values())
    total_verifiable = stats["correct"] + stats["wrong"]

    print("\n" + "=" * 60)
    print("📊 回测统计报告")
    print("=" * 60)
    print(f"总处理: {total_processed} 条")
    print(f"  ✅ 预测正确: {stats['correct']} 条")
    print(f"  ❌ 预测错误: {stats['wrong']} 条")
    print(f"  🗑️ 删除（无法识别资产）: {stats['no_ticker']} 条")
    print(f"  🗑️ 删除（无数据）: {stats['no_data']} 条")
    print(f"  🗑️ 删除（缺少字段）: {stats['bad_fields']} 条")
    print(f"  ⚠️ 数据库错误: {stats['db_error']} 条")
    print("-" * 60)
    
    if total_verifiable > 0:
        accuracy = stats["correct"] / total_verifiable * 100
        print(f"📈 准确率: {accuracy:.1f}% ({stats['correct']}/{total_verifiable})")
    else:
        print("📈 没有可验证的数据")
    
    print("=" * 60)
    print(f"\n🎉 回测完成")


if __name__ == "__main__":
    main()
