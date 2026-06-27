"""信息精选系统 - Digest 生成器 v3
底层逻辑 + 思维模型 + 行动建议"""
import json
from datetime import datetime
import db
import config
import cluster as topic_cluster


def build_digest(period="morning"):
    """生成 Digest：底层逻辑版"""
    candidates = topic_cluster.get_clustered_digest_candidates(
        max_items=config.DIGEST_MAX_ITEMS,
        quality_threshold=config.QUALITY_THRESHOLD,
        dedup_hours=config.DEDUP_WINDOW_HOURS,
    )

    if not candidates:
        print("没有高质量候选内容")
        return None

    today = datetime.utcnow().strftime("%Y-%m-%d")
    time_label = "早" if period == "morning" else "晚"
    title = f"🧠 底层逻辑 · {today} {time_label}"

    lines = [title, "=" * 40, ""]

    for i, item in enumerate(candidates, 1):
        score = item["quality_score"]

        # 标题行
        lines.append(f"**{i}. {item['title'][:65]}**")
        lines.append(f"   {'🔴' if score >= 8 else '🟡' if score >= 7 else '🟢'} {score}/10 | {item['source_name']}")
        lines.append("")

        # 底层逻辑（核心）
        one_liner = item.get("one_liner", "")
        if one_liner and len(one_liner) > 10:
            lines.append(f"   ⚡ **{one_liner}**")
            lines.append("")

        # 洞见（包含思维模型、行动建议、反驳）
        insight = item.get("insight", "")
        if insight and insight not in ("洞察或null", "null", ""):
            for line in insight.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("[底层逻辑]"):
                    lines.append(f"   🔑 {line[6:]}")
                elif line.startswith("[思维模型]"):
                    lines.append(f"   🧰 {line[6:]}")
                elif line.startswith("[所以你应该]"):
                    lines.append(f"   👉 {line[7:]}")
                elif line.startswith("[反驳]"):
                    lines.append(f"   ⚔️ {line[4:]}")
                else:
                    lines.append(f"   {line}")
            lines.append("")

        # 聚类
        members = item.get("_cluster_members", [])
        if len(members) > 1:
            lines.append(f"   📚 同类: {' / '.join(members[1:3])}")
            lines.append("")

        # 链接
        if item.get("url"):
            lines.append(f"   📎 {item['url']}")
            lines.append("")

        lines.append("---")
        lines.append("")

    body = "\n".join(lines)

    conn = db.get_db()
    digest_id = db.create_digest(conn, today, period, title, body, len(candidates))
    if digest_id:
        for i, item in enumerate(candidates):
            db.add_digest_item(conn, digest_id, item["id"], i)
    conn.close()

    print(f"Digest: {title} ({len(candidates)} 条)")
    return {"id": digest_id, "title": title, "body": body, "count": len(candidates)}


if __name__ == "__main__":
    digest = build_digest()
    if digest:
        print("\n" + digest["body"])
