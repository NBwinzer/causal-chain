import os
import json
import finnhub
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)

def get_price(symbol: str, date_str: str):
    """获取指定日期的收盘价，失败返回 None"""
    if not symbol or symbol == 'unknown':
        return None
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        start_ts = int(date_obj.timestamp())
        end_ts = start_ts + 24 * 60 * 60
        
        res = finnhub_client.stock_candles(symbol, 'D', start_ts, end_ts)
        if res.get('s') == 'ok' and res.get('c'):
            return res['c'][0]
        else:
            print(f"⚠️ {symbol} {date_str} 无数据 (s={res.get('s')})")
            return None
    except Exception as e:
        print(f"⚠️ {symbol} {date_str} 查询失败: {e}")
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
        
        if not asset or asset == 'unknown':
            print(f"⏭️ 跳过: 无有效资产代码")
            continue
        
        event_date = occ['trigger_event_date']
        end_date = (datetime.strptime(event_date, '%Y-%m-%d') + timedelta(days=14)).strftime('%Y-%m-%d')
        
        start_price = get_price(asset, event_date)
        end_price = get_price(asset, end_date)
        
        if start_price is None or end_price is None:
            print(f"⏭️ {asset}: 价格获取失败，跳过回测")
            continue
        
        change = (end_price - start_price) / start_price
        actual_dir = 'up' if change > 0.01 else ('down' if change < -0.01 else 'neutral')
        pred_dir = final_impact.get('direction', 'neutral')
        
        # ===== 权重调整 =====
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
        
        # 存储价格并更新状态
        supabase.table('path_occurrences').update({
            'verification_status': status,
            'verified_at': datetime.now(timezone.utc).isoformat(),
            'occurrence_weight': new_weight,
            'start_price': start_price,
            'end_price': end_price,
            'actual_outcome': {
                'start_price': start_price,
                'end_price': end_price,
                'change_percent': change,
                'actual_direction': actual_dir
            }
        }).eq('id', occ['id']).execute()
        
        # ===== 更新路径权重 =====
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
    run_backtest()
