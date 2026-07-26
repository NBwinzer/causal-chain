import os
import json
import hashlib
import feedparser
from datetime import datetime, timezone
from supabase import create_client, Client
from openai import OpenAI

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
nvidia_client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY
)

PROMPT_TEMPLATE = """
You are a financial causal reasoning expert. Analyze the following news and produce TWO outputs:

PART 1 - Summary: A concise 50-80 word summary of the news.
PART 2 - Causal Chain: A step-by-step causal reasoning chain.

News: {event}

Output only JSON in this exact format:
{{
  "summary": "concise 50-80 word summary",
  "causal_chain": {{
    "event_type": "earnings_beat|earnings_miss|rate_hike|rate_cut|product_launch|merger|regulatory|macro|supply_chain|other",
    "steps": [
      {{"step": 1, "channel": "direct|supply_chain|competitor|sector|macro", "description": "step description", "affected_assets": ["CODE"], "direction": "up|down|neutral", "probability": 0.8}}
    ],
    "final_impact": {{"primary_asset": "CODE", "direction": "up|down|neutral", "probability": 0.8, "reasoning": "why"}}
  }},
  "confidence": 0.8
}}
Only JSON, no extra text.
"""

def fetch_rss():
    feeds = [
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://finance.yahoo.com/news/rssindex",
        "https://feeds.marketwatch.com/marketwatch/topstories",
        "https://www.reuters.com/rssfeed/businessNews",
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://www.economist.com/feeds/print-sections/77/finance-and-economics.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"
    ]
    articles = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                articles.append(entry.title)
        except Exception as e:
            print(f"⚠️ RSS feed failed: {url} - {e}")
            continue
    seen = set()
    unique = []
    for a in articles:
        if a not in seen and a:
            seen.add(a)
            unique.append(a)
    return unique[:50]

def generate_path_signature(causal_chain: dict) -> str:
    steps = causal_chain.get('steps', [])
    step_count = len(steps)
    channel_str = '->'.join([s.get('channel', 'unknown') for s in steps])
    direction_str = '->'.join([s.get('direction', 'neutral') for s in steps])
    primary_asset = causal_chain.get('final_impact', {}).get('primary_asset', 'unknown')
    asset_type = 'tech' if primary_asset in ['NVDA', 'AMD', 'INTC', 'AAPL', 'MSFT', 'GOOGL', 'META', 'TSLA'] else 'other'
    signature = f"{step_count}|{channel_str}|{direction_str}|{asset_type}"
    return hashlib.md5(signature.encode()).hexdigest()[:16]

def extract_json(raw: str) -> str:
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()
    start = raw.find('{')
    end = raw.rfind('}') + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    return raw

def get_or_create_path(signature: str, causal_chain: dict) -> int:
    existing = supabase.table('causal_paths') \
        .select('id') \
        .eq('path_signature', signature) \
        .execute()
    if existing.data and len(existing.data) > 0:
        return existing.data[0]['id']
    path_data = {
        'path_signature': signature,
        'path_type': causal_chain.get('event_type', 'other'),
        'description': f"Path: {signature[:8]}...",
        'steps_template': causal_chain.get('steps', []),
        'final_impact_template': causal_chain.get('final_impact', {}),
        'path_weight': 1.0,
        'total_occurrences': 1
    }
    result = supabase.table('causal_paths').insert(path_data).execute()
    return result.data[0]['id']

def generate_chain_with_history(text: str):
    try:
        resp = nvidia_client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[
                {"role": "system", "content": "You are a financial expert. Output only valid JSON."},
                {"role": "user", "content": PROMPT_TEMPLATE.format(event=text)}
            ],
            temperature=0.1,
            max_tokens=1500
        )
        raw = resp.choices[0].message.content
        cleaned = extract_json(raw)
        data = json.loads(cleaned)
        summary = data.get('summary', '')
        causal_chain = data.get('causal_chain', {})
        confidence = data.get('confidence', 0.7)
        signature = generate_path_signature(causal_chain)
        path_id = get_or_create_path(signature, causal_chain)
        return {
            'summary': summary,
            'causal_chain': causal_chain,
            'confidence': confidence,
            'path_signature': signature,
            'path_id': path_id
        }
    except Exception as e:
        print(f"❌ AI生成失败: {e}")
        return None

def save_to_db(result: dict, title: str, source: str):
    if not result:
        return
    causal_chain = result['causal_chain']
    summary = result['summary']
    path_id = result['path_id']
    confidence = result['confidence']
    now_utc = datetime.now(timezone.utc)
    event_date = now_utc.date().isoformat()
    steps = causal_chain.get('steps', [])
    final_impact = causal_chain.get('final_impact', {})
    occurrence_data = {
        'path_id': path_id,
        'trigger_event_title': title[:200],
        'trigger_event_date': event_date,
        'trigger_source': source,
        'trigger_entity': final_impact.get('primary_asset', ''),
        'filled_steps': steps,
        'final_impact': final_impact,
        'verification_status': 'pending',
        'occurrence_weight': 1.0,
        'ai_initial_confidence': confidence,
        'ai_final_confidence': confidence
    }
    occ_result = supabase.table('path_occurrences').insert(occurrence_data).execute()
    if occ_result.data:
        print(f"✅ 实例入库: {title[:40]}...")
    event_data = {
        'title': title[:200],
        'ai_summary': summary,
        'event_date': event_date,
        'source': source
    }
    supabase.table('events').insert(event_data).execute()

def main():
    print(f"🚀 RSS 因果链抓取开始: {datetime.now(timezone.utc)}")
    news = fetch_rss()
    print(f"📰 共抓取 {len(news)} 条新闻")
    for idx, item in enumerate(news, 1):
        print(f"\n🔹 [{idx}/{len(news)}] {item[:50]}...")
        result = generate_chain_with_history(item)
        if result:
            save_to_db(result, item, 'RSS')

if __name__ == "__main__":
    main()
