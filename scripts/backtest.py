#!/usr/bin/env python3
"""
Inchest 回测脚本 - 使用 yfinance（免费）
读取 path_occurrences 表，获取实际价格，更新验证状态
"""

import os
import json
import time
from datetime import datetime, timedelta
import yfinance as yf
from supabase import create_client

# 配置
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_price(symbol, date):
    """获取指定日期的收盘价"""
    if not symbol:
        return None
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=date - timedelta(days=1), end=date + timedelta(days=1))
        if not hist.empty:
            return hist['Close'].iloc[-1]
    except Exception as e:
        print(f"⚠️ {symbol} 价格获取失败: {e}")
    return None

def get_price_after_days(symbol, event_date, days=5):
    """获取事件发生后第 N 天的收盘价"""
    target_date = event_date + timedelta(days=days)
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=event_date - timedelta(days=1), end=target_date + timedelta(days=2))
        if not hist.empty:
            for idx in hist.index:
                if idx.date() >= target_date:
                    return hist.loc[idx]['Close']
            return hist['Close'].iloc[-1]
    except Exception as e:
        print(f"⚠️ {symbol} 价格获取失败: {e}")
    return None

def main():
    print(f"🚀 启动回测: {datetime.now()}")

    # 获取待回测的记录（最近 30 天的事件，且尚未验证）
    cutoff = (datetime.now() - timedelta(days=30)).date()
    pending = supabase.table("path_occurrences")\
        .select("*")\
        .eq("verification_status", "pending")\
        .gte("trigger_event_date", cutoff.isoformat())\
        .execute()

    print(f"🔍 找到 {len(pending.data)} 条待回测记录")

    if not pending.data:
        print("✅ 无待回测记录")
        return

    success_count = 0
    for item in pending.data:
        idx = item["id"]
        event_date = datetime.fromisoformat(item["trigger_event_date"]).date()
        final_impact = item.get("final_impact", {})
        asset = final_impact.get("asset")
        predicted = final_impact.get("direction")

        if not asset or not predicted:
            print(f"⏭️ 跳过 ID={idx}: 缺少 asset 或 direction")
            continue

        # 获取价格
        price_after = get_price_after_days(asset, event_date, days=5)
        if price_after is None:
            print(f"⏭️ {asset} {event_date} 价格获取失败，跳过")
            continue

        price_before = get_price(asset, event_date - timedelta(days=1))
        if price_before is None:
            print(f"⏭️ {asset} 基准价格获取失败，跳过")
            continue

        # 计算实际方向
        change_pct = (price_after - price_before) / price_before
        if change_pct > 0.02:
            actual = "up"
        elif change_pct < -0.02:
            actual = "down"
        else:
            actual = "neutral"

        is_correct = (predicted == actual)
        status = "verified" if is_correct else "failed"

        # 更新数据库
        supabase.table("path_occurrences").update({
            "verification_status": status,
            "actual_outcome": {
                "direction": actual,
                "change_percent": round(change_pct * 100, 2),
                "price_before": price_before,
                "price_after": price_after
            },
            "verified_at": datetime.now().isoformat()
        }).eq("id", idx).execute()

        print(f"{'✅' if is_correct else '❌'} {asset}: 预测 {predicted} 实际 {actual} ({change_pct*100:.2f}%)")
        success_count += 1
        time.sleep(0.5)

    print(f"🎉 回测完成，成功处理 {success_count} 条")

if __name__ == "__main__":
    main()
