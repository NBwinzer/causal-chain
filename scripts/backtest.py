import os
import re
import json
import time
from collections import Counter
from datetime import datetime, timedelta

import yfinance as yf
from supabase import create_client

# ==================== 配置 ====================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")   # 建议使用 service_role key

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TABLE_NAME = "path_occurrences"

# ========== 资产映射表（你原来的） ==========
ASSET_TO_TICKER = {
    "NVDA": "NVDA", "NVIDIA": "NVDA", "NVIDIA Corporation": "NVDA",
    "AAPL": "AAPL", "Apple": "AAPL", "Apple Inc.": "AAPL",
    "MSFT": "MSFT", "Microsoft": "MSFT", "Microsoft Corp": "MSFT",
    "AMZN": "AMZN", "Amazon": "AMZN", "Amazon.com Inc.": "AMZN",
    "GOOGL": "GOOGL", "GOOG": "GOOGL", "Google": "GOOGL", "Alphabet": "GOOGL",
    "META": "META", "Meta": "META", "Facebook": "META",
    "NFLX": "NFLX", "Netflix": "NFLX",
    "AMD": "AMD", "Advanced Micro Devices": "AMD",
    "INTC": "INTC", "Intel": "INTC",
    "QCOM": "QCOM", "Qualcomm": "QCOM",
    "TXN": "TXN", "Texas Instruments": "TXN",
    "MU": "MU", "Micron": "MU",
    "ARM": "ARM", "Arm Holdings": "ARM",
    "ORCL": "ORCL", "Oracle": "ORCL",
    "CRM": "CRM", "Salesforce": "CRM",
    "ADBE": "ADBE", "Adobe": "ADBE",
    "PYPL": "PYPL", "PayPal": "PYPL",
    "IBM": "IBM",
    "CSCO": "CSCO", "Cisco": "CSCO",
    "AVGO": "AVGO", "Broadcom": "AVGO",
    "JPM": "JPM", "JPMorgan": "JPM", "JPMorgan Chase": "JPM",
    "BAC": "BAC", "Bank of America": "BAC",
    "WFC": "WFC", "Wells Fargo": "WFC",
    "GS": "GS", "Goldman Sachs": "GS",
    "MS": "MS", "Morgan Stanley": "MS",
    "C": "C", "Citigroup": "C",
    "V": "V", "Visa": "V",
    "MA": "MA", "Mastercard": "MA",
    "XOM": "XOM", "Exxon": "XOM", "ExxonMobil": "XOM",
    "CVX": "CVX", "Chevron": "CVX",
    "Oil": "CL=F", "WTI": "CL=F", "Crude": "CL=F", "CL": "CL=F",
    "SPY": "SPY", "S&P 500": "SPY", "SP500": "SPY", "SPX": "^GSPC",
    "BTC": "BTC-USD", "Bitcoin": "BTC-USD",
    "ETH": "ETH-USD", "Ethereum": "ETH-USD",
    "Gold": "GC=F", "GC": "GC=F",
    "USD": "UUP", "GBP": "FXB", "INR": "INR=X", "AUD": "FXA",
    "Nasdaq": "^IXIC", "IXIC": "^IXIC",
    "Dow": "^DJI", "DJI": "^DJI",
    "Nifty": "^NSEI", "NSEI": "^NSEI",
    "TLT": "TLT",
    "VYM": "VYM",
    "XLF": "XLF",
    "XLK": "XLK",
    "XLE": "XLE",
    "IWM": "IWM",
    "EEM": "EEM",
    "EFA": "EFA",
    "SOXX": "SOXX",
    "AIQ": "AIQ",
}


# ==================== 核心：基于 steps_template 匹配真实路径 ====================

def extract_keywords_from_text(text):
    """
    从文本中提取英文关键词（小写，去重，长度>=3）
    """
    if not text:
        return set()
    words = re.findall(r'[a-zA-Z]+', str(text).lower())
    return {w for w in words if len(w) >= 3}


def extract_path_keywords(path):
    """
    从真实路径的 steps_template 和 final_impact_template 中提取所有关键词
    返回: set of keywords
    """
    keywords = set()
    
    # 1. 从 steps_template 提取
    steps = path.get('steps_template')
    if steps:
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except:
                steps = []
        if isinstance(steps, list):
            for step in steps:
                # 提取 affected_assets（最重要）
                assets = step.get('affected_assets', [])
                for asset in assets:
                    if isinstance(asset, str):
                        keywords.update(extract_keywords_from_text(asset))
                # 提取 description
                desc = step.get('description', '')
                if desc:
                    keywords.update(extract_keywords_from_text(desc))
    
    # 2. 从 final_impact_template 提取
    final = path.get('final_impact_template')
    if final:
        if isinstance(final, str):
            try:
                final = json.loads(final)
            except:
                final = {}
        if isinstance(final, dict):
            # primary_asset
            primary = final.get('primary_asset')
            if primary:
                keywords.update(extract_keywords_from_text(primary))
            # reasoning
            reasoning = final.get('reasoning')
            if reasoning:
                keywords.update(extract_keywords_from_text(reasoning))
            # affected_assets
            assets = final.get('affected_assets', [])
            for asset in assets:
                if isinstance(asset, str):
                    keywords.update(extract_keywords_from_text(asset))
    
    # 3. 从 path_signature 补一点（兜底）
    sig = path.get('path_signature', '')
    if sig:
        keywords.update(extract_keywords_from_text(sig))
    
    return keywords


def build_path_index(all_paths):
    """
    构建路径索引: [(path_obj, keywords_set), ...]
    排除 UNKNOWN_GENERIC（作为兜底）
    """
    indexed = []
    for path in all_paths:
        if path.get('path_signature') == 'UNKNOWN_GENERIC':
            continue
        keywords = extract_path_keywords(path)
        if keywords:
            indexed.append((path, keywords))
        else:
            # 如果路径完全没有关键词（理论上不会），用 path_signature 做最低匹配
            sig_keywords = extract_keywords_from_text(path.get('path_signature', ''))
            if sig_keywords:
                indexed.append((path, sig_keywords))
    return indexed


def match_path_by_event(event_title, path_index):
    """
    用事件标题匹配路径索引
    返回: (path_obj, score) 或 (None, 0)
    """
    if not event_title or not path_index:
        return None, 0
    
    event_words = extract_keywords_from_text(event_title)
    if not event_words:
        return None, 0
    
    best_path = None
    best_score = 0.0
    
    for path, path_keywords in path_index:
        intersection = event_words & path_keywords
        if not intersection:
            continue
        
        # 得分 = 交集中关键词数量 / 路径关键词总数量（路径关键词越少越精准）
        # 再加一个加权：如果交集中包含 "asset" 类的词，权重更高（但我们做统一处理）
        score = len(intersection) / len(path_keywords) if path_keywords else 0
        
        # 如果匹配到了完整的关键词集合，额外加分
        if intersection == path_keywords and len(path_keywords) > 0:
            score += 0.3
        
        if score > best_score:
            best_score = score
            best_path = path
    
    # 阈值：得分低于 0.15 视为不匹配（避免误匹配）
    if best_score < 0.15:
        return None, 0
    
    return best_path, best_score


# ==================== 资产识别 ====================

def get_ticker_from_entity(entity):
    if not entity:
        return None
    if entity in ASSET_TO_TICKER:
        return ASSET_TO_TICKER[entity]
    entity_lower = entity.lower()
    for name, ticker in ASSET_TO_TICKER.items():
        if name.lower() in entity_lower:
            return ticker
    return None


def get_price_change(ticker, event_date, days=5):
    try:
        if isinstance(event_date, str):
            start = datetime.strptime(event_date, "%Y-%m-%d")
        else:
            start = event_date
        end = start + timedelta(days=days + 1)
        stock = yf.Ticker(ticker)
        hist = stock.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if hist.empty or len(hist) < 2:
            return None
        open_price = hist["Open"].iloc[0]
        close_price = hist["Close"].iloc[-1]
        return (close_price - open_price) / open_price * 100
    except Exception:
        return None


# ==================== 主回测逻辑 ====================

def main():
    print(f"🔄 回测开始: {datetime.now().isoformat()}")

    # ---- 1. 加载所有路径，构建索引 ----
    all_paths = supabase.table('causal_paths').select('*').execute().data
    print(f"📚 加载 {len(all_paths)} 条路径，构建匹配索引...")
    
    path_index = build_path_index(all_paths)
    print(f"   ✅ {len(path_index)} 条真实路径参与匹配（UNKNOWN_GENERIC 作为兜底）")
    
    # 显示几条路径的关键词示例（调试用）
    for path, keywords in path_index[:3]:
        print(f"   📌 {path.get('path_signature', '')[:12]}... -> {len(keywords)} 个关键词")

    # 获取 UNKNOWN_GENERIC
    unknown_path = next((p for p in all_paths if p['path_signature'] == 'UNKNOWN_GENERIC'), None)
    if not unknown_path:
        resp = supabase.table('causal_paths').insert({
            'path_signature': 'UNKNOWN_GENERIC',
            'path_description': '未分类通用路径（兜底）',
            'trigger_type': 'UNKNOWN',
            'trigger_keywords': []
        }).execute()
        unknown_path = resp.data[0]

    # ---- 2. 查询待回测记录 ----
    response = supabase.table(TABLE_NAME)\
        .select("*")\
        .eq("verification_status", "pending")\
        .limit(100)\
        .execute()

    records = response.data
    if not records:
        print("✅ 没有待回测的记录")
        return

    print(f"📊 找到 {len(records)} 条待回测记录")

    # ---- 3. 统计 ----
    correct_count = 0
    wrong_count = 0
    deleted_no_ticker = 0
    deleted_no_data = 0
    missing_fields = 0
    matched_to_real = 0
    matched_to_unknown = 0

    for rec in records:
        rec_id = rec["id"]
        final_impact = rec.get("final_impact", {})
        if isinstance(final_impact, str):
            try:
                final_impact = json.loads(final_impact)
            except:
                final_impact = {}
        
        predicted_dir = final_impact.get("direction", "")
        # 处理 up|down 这种多值
        if '|' in predicted_dir:
            predicted_dir = predicted_dir.split('|')[0]
        
        entity = rec.get("trigger_entity", "")
        event_date = rec.get("trigger_event_date")
        trigger_title = rec.get("trigger_event_title", "")

        # ---- 缺少字段 → 删除 ----
        if not event_date or not predicted_dir or not entity:
            supabase.table(TABLE_NAME).delete().eq("id", rec_id).execute()
            missing_fields += 1
            print(f"🗑️ 缺少字段，删除: id={rec_id}")
            continue

        # ---- 无法识别资产 → 删除 ----
        ticker = get_ticker_from_entity(entity)
        if not ticker:
            supabase.table(TABLE_NAME).delete().eq("id", rec_id).execute()
            deleted_no_ticker += 1
            print(f"🗑️ 无法识别资产，删除: {entity}")
            continue

        # ---- 获取价格 ----
        change = get_price_change(ticker, event_date, days=5)
        if change is None:
            supabase.table(TABLE_NAME).delete().eq("id", rec_id).execute()
            deleted_no_data += 1
            print(f"🗑️ 无数据，删除: {ticker} ({entity})")
            continue

        # ---- 判断实际方向 ----
        if change > 0.5:
            actual_dir = "up"
        elif change < -0.5:
            actual_dir = "down"
        else:
            actual_dir = "neutral"

        is_correct = (predicted_dir == actual_dir)

        # ---- ⭐ 核心：用 steps_template 匹配真实路径 ----
        matched_path, score = match_path_by_event(trigger_title, path_index)
        
        if matched_path:
            path_id = matched_path['id']
            matched_to_real += 1
            print(f"   🎯 匹配到路径: {matched_path.get('path_signature', '')[:12]}... (得分: {score:.2f})")
        else:
            path_id = unknown_path['id']
            matched_to_unknown += 1
            print(f"   ⚠️ 无匹配路径 (最高分: {score:.2f})，使用 UNKNOWN_GENERIC")

        # ---- 更新路径统计 ----
        try:
            supabase.rpc('update_path_stats', {
                'p_path_id': path_id,
                'p_predicted_direction': predicted_dir,
                'p_actual_direction': actual_dir,
                'p_event_title': trigger_title,
                'p_ticker': ticker
            }).execute()
        except Exception as e:
            print(f"   ⚠️ 更新路径统计失败: {e}")

        # ---- 更新原记录 ----
        supabase.table(TABLE_NAME).update({
            "verification_status": "verified" if is_correct else "failed",
            "verified_at": datetime.now().isoformat(),
            "actual_outcome": {
                "direction": actual_dir,
                "change_percent": round(change, 2),
                "ticker": ticker
            },
            "path_id": path_id
        }).eq("id", rec_id).execute()

        if is_correct:
            correct_count += 1
            print(f"✅ {entity}({ticker}) 预测:{predicted_dir} 实际:{actual_dir} ({change:+.1f}%)")
        else:
            wrong_count += 1
            print(f"❌ 预测错误 {entity}({ticker}) 预测:{predicted_dir} 实际:{actual_dir} ({change:+.1f}%)")

        time.sleep(0.5)

    # ---- 统计报告 ----
    total_processed = correct_count + wrong_count + deleted_no_ticker + deleted_no_data + missing_fields
    total_verifiable = correct_count + wrong_count

    print("\n" + "="*60)
    print("📊 回测统计报告")
    print("="*60)
    print(f"总处理: {total_processed} 条")
    print(f"  ✅ 预测正确: {correct_count} 条")
    print(f"  ❌ 预测错误: {wrong_count} 条")
    print(f"  🗑️ 删除（无法识别资产）: {deleted_no_ticker} 条")
    print(f"  🗑️ 删除（无数据）: {deleted_no_data} 条")
    print(f"  🗑️ 删除（缺少字段）: {missing_fields} 条")
    print("-"*60)
    print(f"  🎯 匹配到真实路径: {matched_to_real} 条")
    print(f"  ⚠️ 落到 UNKNOWN_GENERIC: {matched_to_unknown} 条")
    print("-"*60)
    
    if total_verifiable > 0:
        accuracy = correct_count / total_verifiable * 100
        print(f"📈 准确率: {accuracy:.1f}% ({correct_count}/{total_verifiable})")
    else:
        print("📈 没有可验证的数据")
    
    print("="*60)
    print(f"\n🎉 回测完成")


if __name__ == "__main__":
    main()
