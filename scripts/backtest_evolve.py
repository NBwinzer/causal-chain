import os
import json
import yfinance as yf
from datetime import datetime, timezone, timedelta
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
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).date().isoformat()
    res = supabase.table('path_occurrences') \
        .select('*') \
        .eq('verification_status', 'pending') \
        .lte('trigger_event_date', cutoff) \
        .execute()
    occurrences = res.data
    print(f"🔍 待回测: {len(occurrences)} 条")
    for occ in occurrences:
        final_impact = occ.get('final_impact', {})
        asset = final_impact.get('primary_asset')
        if not asset:
            continue
        start_price = get_price(asset, occ['trigger_event_date'])
        end_date = (datetime.strptime(occ['trigger_event_date'], '%Y-%m-%d') + timedelta(days=14)).strftime('%Y-%m-%d')
        end_price = get_price(asset, end_date)
        if not start_price or not end_price:
            print(f"⏭️ {asset}: 价格获取失败")
            continue
        change = (end_price - start_price) / start_price
        actual_dir = 'up' if change > 0.01 else ('down' if change < -0.01 else 'neutral')
        pred_dir = final_impact.get('direction', 'neutral')
        if actual_dir == pred_dir:
            status = 'verified'
            weight_delta = 0.05
        else:
            status = 'branch_created'
            weight_delta = -0.05
            branch_chain = occ.get('filled_steps', [])
            new_final_impact = final_impact.copy()
            new_final_impact['direction'] = actual_dir
            branch_data = {
                'path_id': occ.get('path_id'),
                'trigger_event_title': occ.get('trigger_event_title', '') + ' [BRANCH]',
                'trigger_event_date': occ.get('trigger_event_date'),
                'trigger_source': 'BACKTEST_BRANCH',
                'trigger_entity': occ.get('trigger_entity'),
                'filled_steps': branch_chain,
                'final_impact': new_final_impact,
                'verification_status': 'pending',
                'occurrence_weight': 1.0,
                'branch_parent_id': occ.get('id'),
                'branch_reason': f'direction_mismatch: pred_{pred_dir}_actual_{actual_dir}',
                'ai_final_confidence': 0.5
            }
            supabase.table('path_occurrences').insert(branch_data).execute()
            print(f"🌿 分支创建: {occ['id']} → {actual_dir}")
        new_weight = max(0.1, min(2.0, occ.get('occurrence_weight', 1.0) + weight_delta))
        supabase.table('path_occurrences').update({
            'verification_status': status,
            'verified_at': datetime.now(timezone.utc).isoformat(),
            'occurrence_weight': new_weight,
            'actual_outcome': {
                'start_price': start_price,
                'end_price': end_price,
                'change_percent': change,
                'actual_direction': actual_dir
            }
        }).eq('id', occ['id']).execute()
        path_id = occ.get('path_id')
        if path_id:
            path_res = supabase.table('causal_paths') \
                .select('path_weight, correct_count, failed_count') \
                .eq('id', path_id) \
                .execute()
            if path_res.data:
                path = path_res.data[0]
                new_path_weight = max(0.1, min(2.0, path.get('path_weight', 1.0) + weight_delta * 0.5))
                if actual_dir == pred_dir:
                    new_correct = path.get('correct_count', 0) + 1
                    new_failed = path.get('failed_count', 0)
                else:
                    new_correct = path.get('correct_count', 0)
                    new_failed = path.get('failed_count', 0) + 1
                supabase.table('causal_paths').update({
                    'path_weight': new_path_weight,
                    'correct_count': new_correct,
                    'failed_count': new_failed,
                    'last_verified_at': datetime.now(timezone.utc).isoformat()
                }).eq('id', path_id).execute()
        print(f"{'✅' if actual_dir == pred_dir else '🔄'} {asset}: pred={pred_dir} actual={actual_dir} ({change:.2%}) weight={new_weight:.2f}")

if __name__ == "__main__":
    run_backtest()import os
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
