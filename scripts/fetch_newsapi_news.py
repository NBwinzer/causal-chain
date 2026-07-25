import os
import json
from datetime import datetime, timedelta
from newsapi import NewsApiClient
from supabase import create_client, Client
from openai import OpenAI

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

NEWS_API_KEY = os.environ.get("NEWS_API_KEY")
newsapi = NewsApiClient(api_key=NEWS_API_KEY)

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
nvidia_client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY
)

QUERIES = ["stock market", "earnings", "Fed interest rate", "inflation", "AI chip", "oil price"]

SOURCE_WEIGHT = {
    'Finnhub': 1.2,
    'NewsAPI': 0.9,
    'RSS': 1.0,
    'BACKTEST_BRANCH': 0.8
}

def fetch_newsapi_news():
    to_date = datetime.now().strftime('%Y-%m-%d')
    from_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    all_news = []
    for query in QUERIES:
        try:
            result = newsapi.get_everything(
                q=query,
                language='en',
                sort_by='publishedAt',
                from_param=from_date,
                to=to_date,
                page_size=5
            )
            for article in result.get('articles', []):
                title = article.get('title', '')
                if title and title != '[Removed]':
                    all_news.append({
                        'title': title,
                        'description': article.get('description', ''),
                        'source': 'NewsAPI',
                        'query': query,
                        'url': article.get('url', '')
                    })
        except Exception as e:
            print(f"⚠️ NewsAPI {query} 失败: {e}")
            continue
    seen = set()
    unique = []
    for item in all_news:
        if item['title'] not in seen:
            seen.add(item['title'])
            unique.append(item)
    print(f"📰 NewsAPI 获取 {len(unique)} 条")
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
    print(f"🚀 NewsAPI 开始: {datetime.now()}")
    news = fetch_newsapi_news()
    for idx, item in enumerate(news, 1):
        print(f"🔹 [{idx}/{len(news)}] {item['title'][:50]}...")
        chain = generate_chain(item['title'])
        if chain:
            save_to_db(chain, item, 'NewsAPI')

if __name__ == "__main__":
    main()
