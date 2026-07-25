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

PROMPT_TEMPLATE = """
分析金融新闻，生成因果推理链 JSON（只输出 JSON）：

新闻：{event}

格式：
{
  "event_summary": "摘要",
  "trigger": {"entity": "主体", "action": "动作", "unexpected": "超预期点"},
  "transmission_channels": [
    {"step": 1, "channel": "传导类型", "description": "描述", "affected_assets": ["CODE"], "direction": "up/down/neutral", "probability": 0.8}
  ],
  "final_impact": {"primary_asset": "CODE", "direction": "up/down/neutral", "probability": 0.8, "reasoning": "理由"},
  "category": "Tech/Finance/Energy/Macro/Consumer",
  "confidence": 0.8
}
"""

def fetch_rss():
    """从 7 个 RSS 源抓取，每个源取前 10 条，最终取前 50 条"""
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
            print(f"⚠️ RSS 源 {url} 解析失败: {e}")
            continue
    unique_articles = list(dict.fromkeys(articles))
    return unique_articles[:50]

def generate_chain(text):
    try:
        resp = nvidia_client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",  # 更稳定的模型
            messages=[
                {"role": "system", "content": "金融推理专家，只输出JSON。"},
                {"role": "user", "content": PROMPT_TEMPLATE.format(event=text)}
            ],
            temperature=0.3,
            max_tokens=1024
        )
        raw = resp.choices[0].message.content
        print(f"📝 原始返回: {raw[:200]}...")  # 调试打印
        
        # 提取 JSON
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        
        # 找到第一个 { 和最后一个 }
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start != -1 and end > start:
            raw = raw[start:end]
        
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"⚠️ JSON 解析失败: {e}")
        print(f"⚠️ 原始内容: {raw[:300] if 'raw' in locals() else '空响应'}")
        return None
    except Exception as e:
        print(f"⚠️ API 调用失败: {e}")
        return None

def save_to_db(chain, title):
    if not chain:
        return
    data = {
        "event_title": title[:100],
        "event_date": datetime.now().date().isoformat(),
        "event_description": chain.get("event_summary", ""),
        "causal_chain": chain,
        "trigger_entity": chain.get("trigger", {}).get("entity"),
        "affected_assets": chain.get("transmission_channels", [{}])[0].get("affected_assets", []),
        "primary_asset": chain.get("final_impact", {}).get("primary_asset"),
        "predicted_direction": chain.get("final_impact", {}).get("direction"),
        "predicted_probability": chain.get("final_impact", {}).get("probability"),
        "category": chain.get("category"),
        "confidence": chain.get("confidence"),
        "verification_status": "pending",
        "source": "RSS"
    }
    try:
        supabase.table("causal_chains").insert(data).execute()
        print(f"✅ 入库成功: {title[:30]}...")
    except Exception as e:
        print(f"❌ 入库失败: {e}")

def main():
    print(f"🚀 因果链抓取开始: {datetime.now()}")
    news = fetch_rss()
    print(f"📰 共抓取 {len(news)} 条新闻")
    success_count = 0
    for idx, item in enumerate(news, 1):
        print(f"🧠 [{idx}/{len(news)}] 处理: {item[:40]}...")
        chain = generate_chain(item)
        if chain:
            save_to_db(chain, item)
            success_count += 1
    print(f"✅ 完成: 成功 {success_count}/{len(news)} 条")

if __name__ == "__main__":
    main()
