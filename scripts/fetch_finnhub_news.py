import os
import json
import hashlib
import finnhub
from datetime import datetime, timezone, timedelta
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

WATCH_LIST = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC", "NFLX", "JPM", "BAC", "XOM"]

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

def fetch_finnhub_news():
    to_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    from_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime('%Y-%m-%d')
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
    supabase.table('path_occurrences').insert(occurrence_data).execute()
    print(f"✅ 实例入库: {title[:40]}...")
    event_data = {
        'title': title[:200],
        'ai_summary': summary,
        'event_date': event_date,
        'source': source
    }
    supabase.table('events').insert(event_data).execute()

def main():
    print(f"🚀 Finnhub 开始: {datetime.now(timezone.utc)}")
    news = fetch_finnhub_news()
    for idx, item in enumerate(news, 1):
        print(f"\n🔹 [{idx}/{len(news)}] {item['title'][:50]}...")
        result = generate_chain_with_history(item['title'])
        if result:
            save_to_db(result, item['title'], 'Finnhub')

if __name__ == "__main__":
    main()import os
import json
import hashlib
import finnhub
from datetime import datetime, timezone, timedelta
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

WATCH_LIST = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC", "NFLX", "JPM", "BAC", "XOM"]

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

def fetch_finnhub_news():
    to_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    from_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime('%Y-%m-%d')
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
    supabase.table('path_occurrences').insert(occurrence_data).execute()
    print(f"✅ 实例入库: {title[:40]}...")
    event_data = {
        'title': title[:200],
        'ai_summary': summary,
        'event_date': event_date,
        'source': source
    }
    supabase.table('events').insert(event_data).execute()

def main():
    print(f"🚀 Finnhub 开始: {datetime.now(timezone.utc)}")
    news = fetch_finnhub_news()
    for idx, item in enumerate(news, 1):
        print(f"\n🔹 [{idx}/{len(news)}] {item['title'][:50]}...")
        result = generate_chain_with_history(item['title'])
        if result:
            save_to_db(result, item['title'], 'Finnhub')

if __name__ == "__main__":
    main()import os
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
