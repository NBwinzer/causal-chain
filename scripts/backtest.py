import os
import re
import yfinance as yf
from supabase import create_client
from datetime import datetime, timedelta
import time

# Supabase 配置（从环境变量读取）
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 常见资产代码映射（如果标题中无法直接提取，可用此表）
TICKER_MAP = {
    "NVIDIA": "NVDA",
    "Apple": "AAPL",
    "Microsoft": "MSFT",
    "Amazon": "AMZN",
    "Google": "GOOGL",
    "Tesla": "TSLA",
    "Meta": "META",
    "Netflix": "NFLX",
    "S&P 500": "^GSPC",
    "Dow Jones": "^DJI",
    "Nasdaq": "^IXIC",
    "Oil": "CL=F",
    "Gold": "GC=F",
}

def extract_ticker(text):
    """从事件标题中提取股票代码或资产名称"""
    if not text:
        return None
    
    # 1. 先尝试匹配标准股票代码（大写字母 2-5 个）
    match = re.search(r'\b([A-Z]{2,5})\b', text)
    if match:
        ticker = match.group(1)
        # 过滤掉常见非股票词
        if ticker not in ["AI", "CEO", "CFO", "IPO", "ETF", "FED", "CPI", "GDP"]:
            return ticker
    
    # 2. 检查映射表
    for name, ticker in TICKER_MAP.items():
        if name in text:
            return ticker
    
    return None

def get_price_change(ticker, date_str, days=5):
    """获取指定日期后 N 天的价格变化百分比"""
    try:
        start = datetime.strptime(date_str, "%Y-%m-%d")
        end = start + timedelta(days=days + 1)
        stock = yf.Ticker(ticker)
        hist = stock.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        
        if hist.empty or len(hist) < 2:
            return None
        
        open_price = hist["Open"].iloc[0]
        close_price = hist["Close"].iloc[-1]
        change_pct = (close_price - open_price) / open_price * 100
        return change_pct
    except Exception as e:
        print(f"⚠️ 获取 {ticker} 数据失败: {e}")
        return None

def main():
    print(f"🔄 回测任务开始: {datetime.now().isoformat()}")
    
    # 1. 查询待回测的记录（按预测日期排序）
    response = supabase.table("causal_chains")\
        .select("*")\
        .eq("verification_status", "pending")\
        .order("prediction_date", desc=False)\
        .limit(100)\
        .execute()
    
    records = response.data
    if not records:
        print("✅ 没有待回测的记录")
        return
    
    print(f"📊 找到 {len(records)} 条待回测记录")
    
    success_count = 0
    fail_count = 0
    
    for record in records:
        record_id = record["id"]
        event_title = record.get("event_title", "")
        prediction_date = record.get("prediction_date")
        causal_chain = record.get("causal_chain", {})
        final_impact = causal_chain.get("final_impact", {})
        predicted_direction = final_impact.get("direction")
        
        if not prediction_date or not predicted_direction:
            # 标记为失败，缺少必要字段
            supabase.table("causal_chains")\
                .update({"verification_status": "failed"})\
                .eq("id", record_id)\
                .execute()
            fail_count += 1
            continue
        
        # 提取 ticker
        ticker = extract_ticker(event_title)
        if not ticker:
            # 无法提取代码，跳过并标记失败
            supabase.table("causal_chains")\
                .update({"verification_status": "failed"})\
                .eq("id", record_id)\
                .execute()
            print(f"❌ 无法提取代码: {event_title[:40]}...")
            fail_count += 1
            continue
        
        # 获取实际涨跌幅
        change_pct = get_price_change(ticker, prediction_date, days=5)
        if change_pct is None:
            supabase.table("causal_chains")\
                .update({"verification_status": "failed"})\
                .eq("id", record_id)\
                .execute()
            print(f"❌ 无法获取 {ticker} 数据: {event_title[:40]}...")
            fail_count += 1
            continue
        
        # 判断实际方向
        if change_pct > 1.0:
            actual_direction = "up"
        elif change_pct < -1.0:
            actual_direction = "down"
        else:
            actual_direction = "neutral"
        
        is_correct = predicted_direction == actual_direction
        
        # 更新数据库
        supabase.table("causal_chains")\
            .update({
                "verification_status": "verified" if is_correct else "failed",
                "verified_at": datetime.now().isoformat(),
                "actual_outcome": {
                    "direction": actual_direction,
                    "change_percent": round(change_pct, 2),
                    "ticker": ticker,
                    "days": 5,
                    "predicted": predicted_direction
                }
            })\
            .eq("id", record_id)\
            .execute()
        
        status_emoji = "✅" if is_correct else "❌"
        print(f"{status_emoji} {ticker} 预测:{predicted_direction} 实际:{actual_direction} ({change_pct:+.1f}%) - {event_title[:30]}...")
        success_count += 1
        
        # 避免请求过快
        time.sleep(1)
    
    print(f"🎉 回测完成: {success_count} 条成功, {fail_count} 条失败")


if __name__ == "__main__":
    main()
