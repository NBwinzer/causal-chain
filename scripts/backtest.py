
import os
import yfinance as yf
from supabase import create_client
from datetime import datetime, timedelta
import json
import time

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ASSET_TO_TICKER = {
    "NVDA": "NVDA", "NVIDIA": "NVDA",
    "AAPL": "AAPL", "Apple": "AAPL",
    "MSFT": "MSFT", "Microsoft": "MSFT",
    "AMZN": "AMZN", "Amazon": "AMZN",
    "GOOGL": "GOOGL", "Google": "GOOGL",
    "TSLA": "TSLA", "Tesla": "TSLA",
    "META": "META", "Meta": "META",
    "SPX": "^GSPC", "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC", "IXIC": "^IXIC",
    "Dow": "^DJI", "DJI": "^DJI",
    "Gold": "GC=F",
    "Oil": "CL=F",
}

def get_price_change(ticker, start_date, days=5):
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
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

def verify_path(path):
    """验证单条因果路径"""
    path_id = path["id"]
    final_impact = path.get("final_impact_template", {})
    asset = final_impact.get("asset", "")
    predicted_dir = final_impact.get("direction", "")
    trigger = path.get("trigger_template", "")

    # 找不到资产，标记失败
    if not asset or not predicted_dir:
        supabase.table("causal_paths").update({
            "failed_count": path.get("failed_count", 0) + 1,
            "total_occurrences": path.get("total_occurrences", 0) + 1,
            "path_weight": path.get("path_weight", 0.5) - 0.02,
            "last_verified_at": datetime.now().isoformat()
        }).eq("id", path_id).execute()
        return

    ticker = ASSET_TO_TICKER.get(asset)
    if not ticker:
        supabase.table("causal_paths").update({
            "failed_count": path.get("failed_count", 0) + 1,
            "total_occurrences": path.get("total_occurrences", 0) + 1,
            "path_weight": path.get("path_weight", 0.5) - 0.02,
            "last_verified_at": datetime.now().isoformat()
        }).eq("id", path_id).execute()
        return

    # 使用当前日期作为验证基准（或从 trigger 中提取日期）
    today = datetime.now().date().isoformat()
    change = get_price_change(ticker, today, days=5)

    if change is None:
        # 无法获取数据，跳过本次验证（不更新统计）
        return

    if change > 0.5:
        actual_dir = "up"
    elif change < -0.5:
        actual_dir = "down"
    else:
        actual_dir = "neutral"

    is_correct = predicted_dir == actual_dir

    # 更新统计
    new_total = path.get("total_occurrences", 0) + 1
    new_correct = path.get("correct_count", 0) + (1 if is_correct else 0)
    new_failed = path.get("failed_count", 0) + (0 if is_correct else 1)
    new_weight = new_correct / new_total if new_total > 0 else 0.5

    supabase.table("causal_paths").update({
        "total_occurrences": new_total,
        "correct_count": new_correct,
        "failed_count": new_failed,
        "path_weight": round(new_weight, 3),
        "last_verified_at": datetime.now().isoformat()
    }).eq("id", path_id).execute()

    print(f"{'✅' if is_correct else '❌'} {asset} 预测:{predicted_dir} 实际:{actual_dir} ({change:+.1f}%) 权重:{new_weight:.2f}")

def main():
    print(f"🔄 回测验证开始: {datetime.now().isoformat()}")

    # 查询所有因果路径（或只查询最近需要验证的）
    response = supabase.table("causal_paths")\
        .select("*")\
        .order("last_verified_at", desc=True)\
        .limit(50)\
        .execute()

    paths = response.data
    if not paths:
        print("✅ 没有找到因果路径")
        return

    print(f"📊 找到 {len(paths)} 条路径")

    for path in paths:
        verify_path(path)
        time.sleep(0.5)

    print("🎉 回测验证完成")

if __name__ == "__main__":
    main()
