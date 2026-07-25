import os
import json
import yfinance as yf
from datetime import datetime, timedelta
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_price(symbol: str, date: str):
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=date, end=date)
        if not hist.empty:
            return hist['Close'].iloc[0]
    except Exception as e:
        print(f"⚠️ yfinance {symbol} 失败: {e}")
    return None

def run_backtest():
    cutoff = (datetime.now() - timedelta(days=14)).date().isoformat()
    res = supabase.table('causal_chains') \
        .select('*') \
        .eq('verification_status', 'pending') \
        .lte('event_date', cutoff) \
        .execute()
    
    chains = res.data
    print(f"🔍 待回测: {len(chains)} 条")
    
    for item in chains:
        asset = item.get('primary_asset')
        if not asset:
            continue
        
        start_price = get_price(asset, item['event_date'])
        end_date = (datetime.strptime(item['event_date'], '%Y-%m-%d') + timedelta(days=14)).strftime('%Y-%m-%d')
        end_price = get_price(asset, end_date)
        
        if not start_price or not end_price:
            print(f"⏭️ {asset}: 价格获取失败")
            continue
        
        change = (end_price - start_price) / start_price
        actual_dir = 'up' if change > 0.01 else ('down' if change < -0.01 else 'neutral')
        pred_dir = item['predicted_direction']
        
        if actual_dir == pred_dir:
            new_weight = min(2.0, item.get('chain_weight', 1.0) + 0.05)
            status = 'verified'
        else:
            new_weight = max(0.1, item.get('chain_weight', 1.0) - 0.05)
            status = 'branch_created'
            branch_chain = item['causal_chain']
            branch_chain['final_impact']['direction'] = actual_dir
            supabase.table("causal_chains").insert({
                "event_title": item['event_title'] + " [BRANCH]",
                "event_date": item['event_date'],
                "event_description": item['event_description'],
                "causal_chain": branch_chain,
                "trigger_entity": item['trigger_entity'],
                "affected_assets": item['affected_assets'],
                "primary_asset": item['primary_asset'],
                "predicted_direction": actual_dir,
                "predicted_probability": max(0.3, item.get('predicted_probability', 0.8) - 0.1),
                "category": item['category'],
                "confidence": max(0.3, item.get('confidence', 0.8) - 0.1),
                "chain_weight": 1.0,
                "branch_parent_id": item['id'],
                "version": item.get('version', 1) + 1,
                "verification_status": "pending",
                "source": "BACKTEST_BRANCH"
            }).execute()
            print(f"🌿 分支创建: {item['id']} → {actual_dir}")
        
        supabase.table('causal_chains').update({
            'verification_status': status,
            'verified_at': datetime.now().isoformat(),
            'chain_weight': new_weight,
            'actual_outcome': {
                'change_percent': change,
                'actual_direction': actual_dir
            }
        }).eq('id', item['id']).execute()
        
        print(f"{'✅' if actual_dir == pred_dir else '🔄'} {asset}: pred={pred_dir} actual={actual_dir} ({change:.2%}) weight={new_weight:.2f}")

if __name__ == "__main__":
    run_backtest()
