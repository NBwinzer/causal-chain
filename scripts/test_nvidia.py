import os
import json
from openai import OpenAI

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY
)

test_news = "NVIDIA beats Q4 earnings estimates, data center revenue surges 409%"

prompt = """
Analyze this financial news and generate a causal reasoning chain in JSON format only.

News: %s

Output strictly JSON:
{
  "event_summary": "summary",
  "trigger": {"entity": "code", "action": "action"},
  "transmission_channels": [{"step": 1, "channel": "direct", "description": "desc", "affected_assets": ["CODE"], "direction": "up", "probability": 0.8}],
  "final_impact": {"primary_asset": "CODE", "direction": "up", "probability": 0.8, "reasoning": "reason"},
  "category": "Tech",
  "confidence": 0.8
}
Only JSON, no extra text.
""" % test_news

try:
    resp = client.chat.completions.create(
        model="meta/llama-3.1-70b-instruct",
        messages=[
            {"role": "system", "content": "You are a financial expert. Output only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        max_tokens=1024
    )
    raw = resp.choices[0].message.content
    print("RAW RESPONSE (repr):")
    print(repr(raw))
    print("\nRAW RESPONSE (full):")
    print(raw)
    
    # Try to parse JSON
    cleaned = raw
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()
    start = cleaned.find('{')
    end = cleaned.rfind('}') + 1
    if start != -1 and end > start:
        cleaned = cleaned[start:end]
    
    data = json.loads(cleaned)
    print("\n✅ JSON parsed successfully!")
    print("event_summary:", data.get('event_summary'))
    print("primary_asset:", data.get('final_impact', {}).get('primary_asset'))
    
except Exception as e:
    print("❌ Error:", e)
    if 'raw' in locals():
        print("Raw content:", repr(raw))
