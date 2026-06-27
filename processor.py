"""信息精选系统 - AI 处理层 v3
从信息中提取底层逻辑和思维模型"""
import json
import re
import requests
import config
import db


# ============================================================
#  Stage 1: 快速过滤
# ============================================================
FILTER_PROMPT = """判断这条内容是否值得深度分析。直接输出JSON。

标题：{title}
来源：{source}
前200字：{preview}

输出：{{"accept": true/false}}

值得分析的内容：
- 有独特视角或反直觉结论
- 揭示了某个行业/领域的底层逻辑
- 有可迁移的思维模型
- 对投资/产品/管理有实际启发

不值得的：
- 纯新闻（某公司发布了某产品）
- 标题党、营销文
- 常识性内容
- 纯技术细节（除非有范式意义）

约50%应该accept。"""


# ============================================================
#  Stage 2: 底层逻辑提取
# ============================================================
ANALYSIS_PROMPT = """你是思维模型提取器。不要做新闻摘要——提取底层逻辑。

来源：{source}
标题：{title}
---
{content}
---

输出JSON（不要其他文字）：
{{
  "principle": "这条内容揭示的底层逻辑是什么？用一句话说清楚，要能脱离原文独立成立。",
  "mental_model": "这里有什么可迁移的思维模型？就是换个场景还能用的那个。写成'当你遇到X时，想想Y'的格式。",
  "implication": "这对一个做投资/做生意/做产品的人，具体意味着什么？不要泛泛而谈，要说'所以你应该...'。",
  "counterpoint": "这个观点可能错在哪？最有力的反驳是什么？",
  "category": "投资/产品/管理/行业/科技/创业/思考/其他",
  "quality_score": 7.5
}}

评分0-10。
质量标准：
- 9-10: 这条内容能改变你看待某类问题的方式
- 7-8: 提供了一个有用的框架或反直觉洞察
- 5-6: 有信息量但缺乏深度
- 3-4: 停留在表面

核心要求：
- principle 要锋利——能被引用，能被反驳
- mental_model 要可操作——不是鸡汤，是工具
- implication 要具体——"你应该关注电网接入拍卖机制的投资机会"而不是"你应该关注能源行业"
- counterpoint 要真诚——真的找一个有力反驳，不是走过场"""


def _call_api(prompt, max_tokens=1200):
    """调用 MiMo API"""
    api_key = config.get_xiaomi_api_key()
    if not api_key:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.XIAOMI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }

    try:
        resp = requests.post(
            f"{config.XIAOMI_API_BASE}/chat/completions",
            headers=headers, json=payload, timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        text = (msg.get("content") or "").strip()
        if not text:
            text = (msg.get("reasoning_content") or "").strip()
        return text, data.get("usage", {}).get("total_tokens", 0)
    except Exception as e:
        return None


def _extract_json(text):
    """鲁棒 JSON 提取"""
    if not text:
        return None
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else parts[0]
        if text.startswith("json"):
            text = text[4:]

    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]

    text = re.sub(r'(?<=[^\\])\n(?=[^"]*")', ' ', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        def f(field):
            m = re.search(rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            return m.group(1) if m else None
        def n(field):
            m = re.search(rf'"{field}"\s*:\s*([\d.]+)', text)
            return float(m.group(1)) if m else 5.0
        def b(field):
            m = re.search(rf'"{field}"\s*:\s*(true|false)', text)
            return m.group(1) == "true" if m else False

        return {
            "principle": f("principle") or "",
            "mental_model": f("mental_model") or "",
            "implication": f("implication") or "",
            "counterpoint": f("counterpoint") or "",
            "category": f("category") or "其他",
            "quality_score": n("quality_score"),
            "accept": b("accept"),
        }


def _quick_filter(item, source_name):
    """Stage 1: 快速过滤"""
    preview = (item["content"] or "")[:300]
    prompt = FILTER_PROMPT.format(
        title=item["title"] or "无标题",
        source=source_name,
        preview=preview,
    )
    result = _call_api(prompt, max_tokens=100)
    if not result:
        return True

    text, _ = result
    parsed = _extract_json(text)
    if not parsed:
        return True
    return parsed.get("accept", True)


def _deep_analysis(item, source_name):
    """Stage 2: 底层逻辑提取"""
    content = (item["content"] or "")[:2000]
    prompt = ANALYSIS_PROMPT.format(
        source=source_name,
        title=item["title"] or "无标题",
        content=content,
    )
    result = _call_api(prompt, max_tokens=1200)
    if not result:
        return None

    text, tokens = result
    parsed = _extract_json(text)
    if not parsed:
        return None
    parsed["_tokens"] = tokens
    return parsed


def process_content(item, source_name="unknown"):
    """两阶段处理"""
    if not _quick_filter(item, source_name):
        return False

    result = _deep_analysis(item, source_name)
    if not result:
        return False

    # 把 principle + mental_model + implication + counterpoint 合并为 insight
    parts = []
    if result.get("principle"):
        parts.append(f"[底层逻辑] {result['principle']}")
    if result.get("mental_model"):
        parts.append(f"[思维模型] {result['mental_model']}")
    if result.get("implication"):
        parts.append(f"[所以你应该] {result['implication']}")
    if result.get("counterpoint"):
        parts.append(f"[反驳] {result['counterpoint']}")

    full_insight = "\n".join(parts) if parts else None

    conn = db.get_db()
    ok = db.save_summary(
        conn, item["id"],
        model=f"{config.XIAOMI_MODEL}-v3",
        one_liner=result.get("principle", ""),
        key_points=[
            result.get("mental_model", ""),
            result.get("implication", ""),
        ],
        insight=full_insight,
        category=result.get("category", "其他"),
        quality_score=result.get("quality_score", 5.0),
        tokens_used=result.get("_tokens", 0),
    )
    conn.close()
    return ok


def process_unsummarized(limit=50):
    """处理所有未摘要内容"""
    conn = db.get_db()
    items = db.get_unsummarized_content(conn, limit)
    sources = {s["id"]: s["name"] for s in db.get_active_sources(conn)}
    conn.close()

    if not items:
        print("没有待处理的内容")
        return 0

    print(f"待处理: {len(items)} 条")
    processed = 0
    filtered = 0
    for i, item in enumerate(items):
        src_name = sources.get(item["source_id"], "unknown")
        title = (item["title"] or "")[:40]
        print(f"  [{i+1}/{len(items)}] {title}...", end=" ", flush=True)
        ok = process_content(item, src_name)
        if ok:
            processed += 1
            print("✓")
        else:
            filtered += 1
            print("✗")

    print(f"\n处理完成: {processed} 通过, {filtered} 过滤")
    return processed


def reprocess_all(limit=50):
    """全部重新处理"""
    conn = db.get_db()
    conn.execute("DELETE FROM digest_items")
    conn.execute("DELETE FROM digests")
    conn.execute("DELETE FROM summaries")
    conn.commit()
    items = conn.execute("SELECT COUNT(*) FROM content").fetchone()[0]
    conn.close()
    print(f"已清除旧摘要，{items} 条待处理")
    return process_unsummarized(limit)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "reprocess":
        reprocess_all()
    else:
        process_unsummarized()
