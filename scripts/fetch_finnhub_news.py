import os
import json
import finnhub
from datetime import datetime, timedelta
from supabase import create_client, Client
from openai import OpenAI

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
nvidia_client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY
)

WATCH_LIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
    "AMD", "INTC", "NFLX", "JPM", "BAC", "XOM"
]

SOURCE_WEIGHT = {
    'Finnhub': 1.2,
    'NewsAPI': 0.9,
    'RSS': 1.0,
    'BACKTEST_BRANCH': 0.8
}

def fetch_finnhub_news():
    to_date = datetime.now().strftime('%Y-%m-%d')
    from_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    all_news = []
    for symbol in WATCH_LIST:
        try:
            news = finnhub_client.company_news(symbol, _from=from_date, to=to_date)
            for item in news[:5]:
                all_news.append({
                    'title': item.get('headline', ''),
                    'date': item.get('datetime', ''),
                    'source': 'Finnhub',
                    'symbol': symbol,
                    'url': item.get('url', '')
                })
        except Exception as e:
            print(f"⚠️ Finnhub {symbol} 失败: {e}")
            continue
    seen = set()
    unique = []
    for item in all_news:
        if item['title'] not in seen and item['title']:
            seen.add(item['title'])
            unique.append(item)
    print(f"📰 Finnhub 获取 {len(unique)} 条")
    return unique

def generate_chain(text: str):
    prompt = f"""Analyze this financial news and generate a causal reasoning chain in JSON format only.

News: {text}

Output strictly JSON:
{{
  "event_summary": "summary",
  "trigger": {{"entity": "code", "action": "action"}},
  "transmission_channels": [{{"step": 1, "channel": "direct", "description": "desc", "affected_assets": ["CODE"], "direction": "up", "probability": 0.8}}],
  "final_impact": {{"primary_asset": "CODE", "direction": "up", "probability": 0.8, "reasoning": "reason"}},
  "category": "Tech",
  "confidence": 0.8
}}
Only JSON, no extra text."""
    try:
        resp = nvidia_client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[
                {"role": "system", "content": "You are a financial expert. Output only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=1024
        )
        raw = resp.choices[0].message.content
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start != -1 and end > start:
            raw = raw[start:end]
        return json.loads(raw)
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        return None

def save_to_db(chain: dict, item: dict, source: str):
    if not chain:
        return
    event_title = item['title'][:100]
    event_date = datetime.now().date().isoformat()
    
    # 查重
    existing = supabase.table('causal_chains') \
        .select('id, chain_weight, confidence, verified_count') \
        .eq('event_title', event_title) \
        .eq('event_date', event_date) \
        .execute()
    
    if existing.data and len(existing.data) > 0:
        old = existing.data[0]
        weight_add = SOURCE_WEIGHT.get(source, 1.0) * 0.3
        new_weight = min(2.0, old.get('chain_weight', 1.0) + weight_add)
        new_confidence = min(0.95, old.get('confidence', 0.8) + 0.05)
        supabase.table('causal_chains').update({
            'chain_weight': new_weight,
            'confidence': new_confidence,
            'verified_count': old.get('verified_count', 1) + 1
        }).eq('id', old['id']).execute()
        print(f"🔁 重复事件，权重累加: {event_title[:40]}... → {new_weight:.2f}")
        return
    
    transmission = chain.get("transmission_channels", [{}])[0]
    final_impact = chain.get("final_impact", {})
    data = {
        "event_title": event_title,
        "event_date": event_date,
        "event_description": chain.get("event_summary", ""),
        "causal_chain": chain,
        "trigger_entity": chain.get("trigger", {}).get("entity"),
        "affected_assets": transmission.get("affected_assets", []),
        "primary_asset": final_impact.get("primary_asset"),
        "predicted_direction": final_impact.get("direction"),
        "predicted_probability": final_impact.get("probability"),
        "category": chain.get("category"),
        "confidence": chain.get("confidence"),
        "chain_weight": 1.0,
        "verified_count": 1,
        "verification_status": "pending",
        "source": source
    }
    try:
        supabase.table("causal_chains").insert(data).execute()
        print(f"✅ 入库: {event_title[:40]}...")
    except Exception as e:
        print(f"❌ 入库失败: {e}")

def main():
    print(f"🚀 Finnhub 开始: {datetime.now()}")
    news = fetch_finnhub_news()
    for idx, item in enumerate(news, 1):
        print(f"🔹 [{idx}/{len(news)}] {item['title'][:50]}...")
        chain = generate_chain(item['title'])
        if chain:
            save_to_db(chain, item, 'Finnhub')

if __name__ == "__main__":
    main()
