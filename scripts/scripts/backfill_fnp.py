import os
import json
import random
from datetime import datetime, timedelta
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

# ===== 模拟 FNSPID 历史数据（100条） =====
# 生产环境替换为真实 CSV 读取逻辑
SAMPLE_NEWS = [
    "Fed raises interest rates by 25 basis points, signals more hikes ahead",
    "Apple reports record quarterly revenue driven by iPhone 15 sales in China",
    "Oil prices plunge 5% on OPEC+ output increase and demand concerns",
    "Tesla unveils full self-driving v12, shares surge 8% after hours",
    "Microsoft closes $68.7B Activision Blizzard acquisition after FTC settlement",
    "NVIDIA Q4 earnings beat estimates, data center revenue jumps 409% YoY",
    "US CPI inflation cools to 3.2% in June, beating expectations of 3.5%",
    "China announces stimulus package for property sector, real estate stocks rally",
    "Amazon Web Services revenue growth slows to 12% amid enterprise cost cutting",
    "Meta launches Threads app, gains 100M users in first week",
    "Goldman Sachs cuts US recession probability to 15% on strong jobs data",
    "Bitcoin reclaims $70,000 level on ETF inflows and halving anticipation",
    "Boeing 737 MAX production restarts after quality control improvements",
    "Saudi Aramco acquires 10% stake in China's Rongsheng Petrochemical",
    "EU passes AI Act with strict regulations on high-risk AI systems",
    "Japan's Nikkei hits all-time high above 42,000 on weak yen and reforms",
    "Starbucks China sales decline 8% as local competitors gain market share",
    "Moderna mRNA flu vaccine shows 90% efficacy in phase 3 trial",
    "TSMC Arizona plant begins mass production of 4nm chips for Apple",
    "Coca-Cola raises full-year guidance on resilient consumer spending"
]
# 扩展到 100 条
historical_news = []
for _ in range(5):
    historical_news.extend(SAMPLE_NEWS)
historical_news = historical_news[:100]

def generate_chain(text):
    try:
        resp = nvidia_client.chat.completions.create(
            model="z-ai/glm-5.2",
            messages=[
                {"role": "system", "content": "金融推理专家，只输出JSON。"},
                {"role": "user", "content": PROMPT_TEMPLATE.format(event=text)}
            ],
            temperature=0.3,
            max_tokens=1024
        )
        raw = resp.choices[0].message.content
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        return json.loads(raw)
    except Exception as e:
        print(f"生成失败: {e}")
        return None

def save_to_db(chain, title, days_ago):
    if not chain:
        return
    event_date = (datetime.now() - timedelta(days=days_ago)).date().isoformat()
    data = {
        "event_title": title[:100],
        "event_date": event_date,
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
        "source": "FNSPID"
    }
    try:
        supabase.table("causal_chains").insert(data).execute()
        print(f"✅ 历史入库 [{days_ago}天前]: {title[:30]}...")
    except Exception as e:
        print(f"❌ 入库失败: {e}")

def main():
    print(f"🚀 开始回填 {len(historical_news)} 条历史数据...")
    for i, item in enumerate(historical_news):
        print(f"处理 {i+1}/{len(historical_news)}: {item[:40]}...")
        chain = generate_chain(item)
        if chain:
            save_to_db(chain, item, days_ago=i+1)

if __name__ == "__main__":
    main()
