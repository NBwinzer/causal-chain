import os
import json
import re
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

PROMPT_TEMPLATE = """
You are a financial causal reasoning expert. Analyze the following financial news and generate a causal reasoning chain in JSON format only.

News: {event}

Output strictly JSON with this structure:
{
  "event_summary": "brief summary of the event",
  "trigger": {"entity": "company or asset code", "action": "what happened"},
  "transmission_channels": [
    {"step": 1, "channel": "direct|supply_chain|competitor|sector|macro", "description": "how it propagates", "affected_assets": ["CODE"], "direction": "up/down/neutral", "probability": 0.8}
  ],
  "final_impact": {"primary_asset": "CODE", "direction": "up/down/neutral", "probability": 0.8, "reasoning": "why"},
  "category": "Tech|Finance|Energy|Macro|Consumer|Healthcare|RealEstate|Other",
  "confidence": 0.8
}

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
        if a not in seen:
            seen.add(a)
            unique.append(a)
    return unique[:50]

def extract_json(raw: str) -> str:
    # 移除 markdown 代码块
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()
    # 找到第一个 { 和最后一个 }
    start = raw.find('{')
    end = raw.rfind('}') + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    return raw

def generate_chain(text: str):
    try:
        resp = nvidia_client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",  # 更稳定
            messages=[
                {"role": "system", "content": "You are a financial expert. Output only valid JSON. No extra text."},
                {"role": "user", "content": PROMPT_TEMPLATE.format(event=text)}
            ],
            temperature=0.1,
            max_tokens=1024
        )
        raw = resp.choices[0].message.content
        
        # 打印原始内容（repr 显示转义字符）
        print(f"📝 RAW (repr): {repr(raw)}")
        print(f"📝 Raw length: {len(raw)}")
        
        cleaned = extract_json(raw)
        print(f"📝 Cleaned (repr): {repr(cleaned)}")
        
        result = json.loads(cleaned)
        print(f"📝 Parsed keys: {list(result.keys())}")
        
        # 验证必要字段
        if 'event_summary' not in result:
            print("⚠️ Missing 'event_summary'")
            return None
        if 'final_impact' not in result or 'primary_asset' not in result['final_impact']:
            print("⚠️ Missing final_impact.primary_asset")
            return None
        return result
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode error: {e}")
        if 'raw' in locals():
            print(f"❌ Raw content: {repr(raw[:1000])}")
        return None
    except Exception as e:
        print(f"❌ API error: {type(e).__name__}: {e}")
        if 'raw' in locals():
            print(f"❌ Raw content: {repr(raw[:500])}")
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
        print(f"\n🔹 [{idx}/{len(news)}] Processing: {item[:50]}...")
        chain = generate_chain(item)
        if chain:
            save_to_db(chain, item)
            success += 1
        else:
            print(f"⏭️ Skipped")
    print(f"\n✅ Done: {success}/{len(news)} successful")

if __name__ == "__main__":
    main()
