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
你是一个金融因果推理专家。以下是一条金融新闻，请生成严格的 JSON 格式的因果推理链。

新闻：{event}

JSON 格式要求（必须严格遵循此格式，不要添加任何其他文本或注释）：
{
  "event_summary": "一句话摘要",
  "trigger": {"entity": "主体公司代码或名称", "action": "动作", "unexpected": "超预期点"},
  "transmission_channels": [
    {"step": 1, "channel": "direct|supply_chain|competitor|sector|macro", "description": "描述", "affected_assets": ["AAPL"], "direction": "up", "probability": 0.8}
  ],
  "final_impact": {"primary_asset": "AAPL", "direction": "up", "probability": 0.8, "reasoning": "理由"},
  "category": "Tech",
  "confidence": 0.8
}

只输出 JSON，不要任何额外文字。
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
            print(f"⚠️ RSS 源 {url} 解析失败: {e}")
            continue
    unique_articles = list(dict.fromkeys(articles))
    return unique_articles[:50]

def extract_json(raw):
    """从混合文本中提取 JSON"""
    # 尝试找 ```json ... ``` 代码块
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()
    
    # 尝试找第一个 { 和最后一个 }
    start = raw.find('{')
    end = raw.rfind('}') + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    
    # 清理换行符和多余空格
    raw = re.sub(r'\n\s*', ' ', raw)
    return raw

def generate_chain(text):
    try:
        resp = nvidia_client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[
                {"role": "system", "content": "你是一个金融因果推理专家。只输出有效的JSON格式数据，不要添加任何额外文字、注释或解释。"},
                {"role": "user", "content": PROMPT_TEMPLATE.format(event=text)}
            ],
            temperature=0.1,  # 降低温度使输出更确定
            max_tokens=1024
        )
        raw = resp.choices[0].message.content
        print(f"📝 原始返回: {raw[:300]}...")
        
        # 尝试提取 JSON
        cleaned = extract_json(raw)
        result = json.loads(cleaned)
        
        # 验证必要字段
        if 'final_impact' not in result or 'primary_asset' not in result.get('final_impact', {}):
            print(f"⚠️ 缺少必要字段: final_impact.primary_asset")
            return None
        return result
        
    except json.JSONDecodeError as e:
        print(f"⚠️ JSON 解析失败: {e}")
        print(f"⚠️ 处理后内容: {cleaned[:300] if 'cleaned' in locals() else '空响应'}")
        return None
    except Exception as e:
        print(f"⚠️ API 调用失败: {e}")
        return None

def save_to_db(chain, title):
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
        print(f"✅ 入库成功: {title[:30]}...")
    except Exception as e:
        print(f"❌ 入库失败: {e}")
        print(f"❌ 数据: {data}")

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
        else:
            print(f"⏭️ 跳过: {item[:30]}...")
    print(f"✅ 完成: 成功 {success_count}/{len(news)} 条")

if __name__ == "__main__":
    main()
