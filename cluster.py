"""信息精选系统 - 话题聚类
把相似内容合并为一个话题，避免重复推送"""
import json
import re
from collections import defaultdict
import db


def _simple_similarity(text1, text2):
    """简单的词汇重叠相似度（无需 embedding 模型）"""
    if not text1 or not text2:
        return 0.0
    # 提取关键词（去停用词）
    stopwords = set("the a an is are was were be been being have has had do does did "
                    "will would shall should may might can could of to in for on with "
                    "at by from as into through during before after above below between "
                    "and or but not no nor so yet both either neither each every all any "
                    "few more most other some such than too very just about also back "
                    "even still how its it he she they them their this that these those "
                    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好".split())

    def extract_words(text):
        # 英文单词
        en_words = set(re.findall(r'[a-zA-Z]+', text.lower()))
        # 中文 2-gram
        cn_chars = re.findall(r'[\u4e00-\u9fff]', text)
        cn_bigrams = set()
        for i in range(len(cn_chars) - 1):
            cn_bigrams.add(cn_chars[i] + cn_chars[i+1])
        return (en_words - stopwords) | cn_bigrams

    words1 = extract_words(text1)
    words2 = extract_words(text2)
    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2
    return len(intersection) / len(union) if union else 0.0


def cluster_topics(items, threshold=0.15):
    """
    对内容列表做话题聚类
    返回: [{topic_id, representative, members, avg_score}]
    """
    if not items:
        return []

    clusters = []  # [{id, items: [item, ...]}]

    for item in items:
        title = item.get("title") or ""
        one_liner = item.get("one_liner") or ""
        text = f"{title} {one_liner}"

        # 找最相似的已有 cluster
        best_cluster = None
        best_sim = 0.0

        for cluster in clusters:
            rep = cluster["items"][0]
            rep_text = f"{rep.get('title','')} {rep.get('one_liner','')}"
            sim = _simple_similarity(text, rep_text)
            if sim > best_sim:
                best_sim = sim
                best_cluster = cluster

        if best_sim >= threshold and best_cluster:
            best_cluster["items"].append(item)
        else:
            clusters.append({"id": len(clusters), "items": [item]})

    # 构建结果
    result = []
    for cluster in clusters:
        items_in_cluster = cluster["items"]
        # 选质量最高的作为代表
        representative = max(items_in_cluster, key=lambda x: x.get("quality_score", 0))
        avg_score = sum(x.get("quality_score", 0) for x in items_in_cluster) / len(items_in_cluster)
        result.append({
            "topic_id": cluster["id"],
            "representative": representative,
            "members": items_in_cluster,
            "count": len(items_in_cluster),
            "avg_score": avg_score,
        })

    return sorted(result, key=lambda x: x["avg_score"], reverse=True)


def get_clustered_digest_candidates(max_items=8, quality_threshold=5.0, dedup_hours=48):
    """获取聚类后的 digest 候选"""
    conn = db.get_db()
    candidates = db.get_digest_candidates(conn, max_items=50, quality_threshold=quality_threshold, dedup_hours=dedup_hours)
    conn.close()

    if not candidates:
        return []

    # 聚类
    clusters = cluster_topics(candidates, threshold=0.15)

    # 每个 cluster 取代表，总数不超过 max_items
    result = []
    for cluster in clusters[:max_items]:
        rep = cluster["representative"]
        rep["_cluster_count"] = cluster["count"]
        rep["_cluster_members"] = [m["title"] for m in cluster["members"]]
        result.append(rep)

    return result


if __name__ == "__main__":
    candidates = get_clustered_digest_candidates()
    print(f"聚类后候选: {len(candidates)} 个话题")
    for i, c in enumerate(candidates, 1):
        count = c.get("_cluster_count", 1)
        members = c.get("_cluster_members", [])
        print(f"  {i}. [{c['quality_score']}] {c['title'][:50]}")
        if count > 1:
            print(f"     聚合了 {count} 条: {members}")
