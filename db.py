"""信息精选系统 - 数据库操作 (共享 investment-monitor 的 monitor.db,表加 digest_ 前缀)"""
import sqlite3
import json
from datetime import datetime, timedelta
from config import DB_PATH


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_active_sources(conn):
    """获取所有启用的信息源"""
    cur = conn.execute("SELECT * FROM digest_sources WHERE enabled=1 ORDER BY tier, id")
    return [dict(row) for row in cur.fetchall()]


def upsert_content(conn, source_id, external_id, title, url, author, content,
                    content_type="text", published_at=None, word_count=0, tags=None):
    """插入或更新内容（防重）"""
    now = datetime.utcnow().isoformat()
    tags_json = json.dumps(tags, ensure_ascii=False) if tags else None

    try:
        conn.execute("""
            INSERT INTO digest_content (source_id, external_id, title, url, author, content,
                                content_type, published_at, fetched_at, word_count, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (source_id, external_id, title, url, author, content,
              content_type, published_at, now, word_count, tags_json))
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError:
        # 已存在，跳过
        return None


def save_summary(conn, content_id, model, one_liner, key_points, insight,
                 category, quality_score, tokens_used=0):
    """保存 AI 摘要"""
    kp_json = json.dumps(key_points, ensure_ascii=False) if isinstance(key_points, list) else key_points
    now = datetime.utcnow().isoformat()
    try:
        conn.execute("""
            INSERT INTO digest_summaries (content_id, model, one_liner, key_points, insight,
                                   category, quality_score, tokens_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (content_id, model, one_liner, kp_json, insight,
              category, quality_score, tokens_used, now))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_unsummarized_content(conn, limit=20):
    """获取尚未 AI 处理的内容"""
    cur = conn.execute("""
        SELECT c.* FROM digest_content c
        LEFT JOIN digest_summaries s ON c.id = s.content_id
        WHERE s.id IS NULL
        ORDER BY c.fetched_at DESC
        LIMIT ?
    """, (limit,))
    return [dict(row) for row in cur.fetchall()]\


def get_digest_candidates(conn, max_items=8, quality_threshold=5.0, dedup_hours=48):
    """获取 digest 候选条目（高质量 + 未推送 + 去重）"""
    cutoff = (datetime.utcnow() - timedelta(hours=dedup_hours)).isoformat()
    cur = conn.execute("""
        SELECT s.*, c.title, c.url, c.author, c.source_id, src.name as source_name
        FROM digest_summaries s
        JOIN digest_content c ON s.content_id = c.id
        JOIN digest_sources src ON c.source_id = src.id
        LEFT JOIN digest_items di ON s.id = di.summary_id
        WHERE s.quality_score >= ?
          AND di.id IS NULL
          AND s.created_at > ?
        ORDER BY s.quality_score DESC
        LIMIT ?
    """, (quality_threshold, cutoff, max_items))
    return [dict(row) for row in cur.fetchall()]


def create_digest(conn, digest_date, period, title, body, item_count, channel="feishu"):
    """创建 digest 记录"""
    now = datetime.utcnow().isoformat()
    try:
        conn.execute("""
            INSERT INTO digest_digests (digest_date, period, title, body, item_count, sent_at, channel, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (digest_date, period, title, body, item_count, now, channel, now))
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError:
        return None


def add_digest_item(conn, digest_id, summary_id, position, included=True, reason=None):
    """关联 digest 和 summary"""
    conn.execute("""
        INSERT INTO digest_items (digest_id, summary_id, position, included, reason)
        VALUES (?, ?, ?, ?, ?)
    """, (digest_id, summary_id, position, int(included), reason))
    conn.commit()


def update_source_fetched(conn, source_id):
    """更新信息源的最后抓取时间"""
    now = datetime.utcnow().isoformat()
    conn.execute("UPDATE digest_sources SET last_fetched_at=? WHERE id=?", (now, source_id))
    conn.commit()
