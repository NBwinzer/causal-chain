import os
import yfinance as yf
from datetime import datetime, timedelta
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def run_backtest():
    cutoff = (datetime.now() - timedelta(days=14)).date().isoformat()
    res = supabase.table('causal_chains') \
        .select('id, primary_asset, event_date, predicted_direction') \
        .eq('verification_status', 'pending') \
        .lte('event_date', cutoff) \
        .execute()
    
    chains = res.data
    print(f"🔍 找到 {len(chains)} 条待回测链")
    
    for item in chains:
        asset = item.get('primary_asset')
        if not asset:
            continue
        
        try:
            ticker = yf.Ticker(asset)
            start = item['event_date']
            end_dt = datetime.strptime(start, '%Y-%m-%d') + timedelta(days=14)
            end = end_dt.strftime('%Y-%m-%d')
            
            hist = ticker.history(start=start, end=end)
            if len(hist) < 2:
                print(f"⏭️ 跳过 {asset}: 数据不足")
                continue
            
            start_price = hist['Close'].iloc[0]
            end_price = hist['Close'].iloc[-1]
            change = (end_price - start_price) / start_price
            actual_dir = 'up' if change > 0.01 else ('down' if change < -0.01 else 'neutral')
            correct = (actual_dir == item['predicted_direction'])
            
            supabase.table('causal_chains').update({
                'verification_status': 'verified' if correct else 'failed',
                'verified_at': datetime.now().isoformat(),
                'actual_outcome': {
                    'start_price': start_price,
                    'end_price': end_price,
                    'change_percent': change,
                    'actual_direction': actual_dir,
                    'correct': correct
                }
            }).eq('id', item['id']).execute()
            
            status = '✅' if correct else '❌'
            print(f"{status} {asset}: 预测 {item['predicted_direction']}, 实际 {actual_dir} ({change:.2%})")
            
        except Exception as e:
            print(f"⚠️ 回测 {asset} 失败: {e}")

if __name__ == "__main__":
    run_backtest()
