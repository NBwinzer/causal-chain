import os
import json
import feedparser
from datetime import datetime
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
        if a not in seen:
            seen.add(a)
            unique.append(a)
    return unique[:50]

def generate_chain(text: str):
    # 使用和测试脚本完全一样的 Prompt
    prompt = f"""
Analyze this financial news and generate a causal reasoning chain in JSON format only.

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
Only JSON, no extra text.
"""
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
        
        # 提取 JSON（和测试脚本一致）
        cleaned = raw
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()
        start = cleaned.find('{')
        end = cleaned.rfind('}') + 1
        if start != -1 and end > start:
            cleaned = cleaned[start:end]
        
        result = json.loads(cleaned)
        print(f"✅ Parsed: {result.get('event_summary', '')[:50]}...")
        return result
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if 'raw' in locals():
            print(f"Raw: {raw[:200]}...")
        return None

def save_to_db(chain: dict, title: str):
    if not chain:
        return
    transmission = chain.get("transmission_channels", [{}])[0]
    final_impact = chain.get("final_impact", {})
    data = {
        "event_title": title[:100],
        "event_date": datetime.now().date().isoformat(),
        "event_description": chain.get("event_summary", ""),
        "causal_chain": chain,
        "trigger_entity": chain.get("trigger", {}).get("entity"),
        "affected_assets": transmission.get("affected_assets", []),
        "primary_asset": final_impact.get("primary_asset"),
        "predicted_direction": final_impact.get("direction"),
        "predicted_probability": final_impact.get("probability"),
        "category": chain.get("category"),
        "confidence": chain.get("confidence"),
        "verification_status": "pending",
        "source": "RSS"
    }
    try:
        supabase.table("causal_chains").insert(data).execute()
        print(f"✅ Saved: {title[:40]}...")
    except Exception as e:
        print(f"❌ DB insert failed: {e}")

def main():
    print(f"🚀 Ingest started: {datetime.now()}")
    news = fetch_rss()
    print(f"📰 Fetched {len(news)} articles")
    success = 0
    for idx, item in enumerate(news, 1):
        print(f"\n🔹 [{idx}/{len(news)}] {item[:50]}...")
        chain = generate_chain(item)
        if chain:
            save_to_db(chain, item)
            success += 1
    print(f"\n✅ Done: {success}/{len(news)} successful")

if __name__ == "__main__":
    main()
