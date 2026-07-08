"""把 info-digest v1.0 schema 升级为加 digest_ 前缀 (共享 monitor.db 兼容版).

⚠️ 危险脚本: 在共享 db 上运行会改其他系统的表名.
   运行前请确认 DB_PATH 指向正确的文件 (默认 config.DB_PATH).

幂等: 跑多次安全, 已迁移版本自动跳过, 通过 schema_migrations 表跟踪.

SQLite 限制:
- ALTER TABLE RENAME 会自动改表上的索引名 (但索引名不包含表名, 不需要)
- ALTER INDEX RENAME 不存在 → 改用 DROP INDEX + CREATE INDEX
- 索引重建需要拿到原列定义和所属表 — 用 PRAGMA index_info + sqlite_master

用法:
  python migrate_add_prefix.py            # dry-run, 默认安全
  python migrate_add_prefix.py --apply   # 真的改
  python migrate_add_prefix.py --apply /path/to.db
"""
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))


def _now():
    return datetime.now(CST).isoformat()


def _ensure_migration_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT NOT NULL
        )
    """)
    conn.commit()


def _applied_versions(conn):
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def _record_version(conn, version, description):
    conn.execute(
        "INSERT INTO schema_migrations (version, applied_at, description) VALUES (?, ?, ?)",
        (version, _now(), description),
    )
    conn.commit()


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _index_info(conn, index_name):
    """返回 (table, [cols]) 或 None."""
    info = conn.execute(f"PRAGMA index_info({index_name})").fetchall()
    if not info:
        return None
    tbl_row = conn.execute(
        "SELECT tbl_name FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    ).fetchone()
    if not tbl_row:
        return None
    return tbl_row[0], [row[2] for row in info]


def _rename_index(conn, old_name, dry_run, touched):
    """DROP + CREATE 重命名索引. 列定义从 PRAGMA 拿."""
    info = _index_info(conn, old_name)
    if not info:
        return False
    tbl, cols = info
    new_name = old_name.replace("idx_", "idx_digest_", 1)
    cols_str = ", ".join(cols)
    if _table_exists(conn, tbl) is False and not dry_run:
        return False  # 隶属表已被改名
    # 拿不到关联表是 idx_content_published/fetched/category 等,它们当时绑定老 content/summaries
    # 这些表已被 RENAME → 直接对 digest_content/digest_summaries 建索引
    if tbl == "content":
        tbl = "digest_content"
    elif tbl == "summaries":
        tbl = "digest_summaries"
    if not _table_exists(conn, tbl):
        print(f"  ⏭  索引 {old_name} 隶属表 {tbl} 不存在,跳过")
        return False
    print(f"  {'--' if dry_run else '✅'} DROP+CREATE INDEX {old_name} → {new_name} ON {tbl}({cols_str})")
    if not dry_run:
        conn.execute(f"DROP INDEX IF EXISTS {old_name}")
        conn.execute(f"CREATE INDEX {new_name} ON {tbl}({cols_str})")
        touched[0] += 1
    return True


# Migrations: (version, description, [(old, new, idx_list)])
#   - old/new: 表名
#   - idx_list: 该表附属的索引名 (old name); 在 RENAME TABLE 后才不存在的索引会从 _rename_index 处理
MIGRATIONS = [
    (1, "重命名 5 张主表", [
        ("sources", "digest_sources", ["idx_content_source"]),
        ("content", "digest_content", ["idx_content_published", "idx_content_fetched"]),
        ("summaries", "digest_summaries", ["idx_summaries_quality", "idx_summaries_category"]),
        ("digests", "digest_digests", ["idx_digests_date"]),
        ("feedback", "digest_feedback", ["idx_feedback_rating"]),
    ]),
    # 注: digest_items 表原本就以 digest_ 开头,无需迁移; 其他系统表(无前缀)
    # 不在我们 5 张表列表里 → 忽略
]


def migrate(db_path: str, apply: bool = False):
    if not Path(db_path).exists():
        print(f"❌ db 不存在: {db_path}")
        return False

    label = "🟢 APPLY" if apply else "🔍 DRY-RUN"
    print(f"{label} 目标 db: {db_path}")
    print(f"文件大小: {Path(db_path).stat().st_size:,} bytes\n")

    conn = sqlite3.connect(db_path)
    _ensure_migration_table(conn)
    applied = _applied_versions(conn)

    # 1) 列出当前表
    tables = sorted([row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )])
    print(f"📋 当前 db 表 ({len(tables)}):")
    INFO_TABLE = {"sources", "content", "summaries", "digests", "feedback"}
    for t in tables:
        if t.startswith("digest_") or t == "schema_migrations":
            tag, mark = "✓", ""
        elif t in INFO_TABLE:
            tag, mark = "⛔ 无前缀 — 待迁移", ""
        else:
            tag, mark = "(其他系统表 — 不动)", ""
        print(f"  - {t:32s} {tag}")
    print()

    if not apply:
        print("🔍 这是 DRY-RUN 模式,数据库未改动. 加 --apply 真正执行.")
        conn.close()
        return True

    touched = [0]
    for version, desc, ops in MIGRATIONS:
        if version in applied:
            print(f"⏭  migration v{version} 已应用, 跳过: {desc}")
            continue
        print(f">> Migration v{version}: {desc}")
        for old, new, idx_list in ops:
            if _table_exists(conn, new):
                print(f"  ⏭  {old} → {new}: 已存在 (幂等)")
                continue
            if not _table_exists(conn, old):
                print(f"  ⏭  {old} → {new}: 老表不存在, 跳过")
                continue
            print(f"  ✅ RENAME TABLE {old} → {new}")
            conn.execute(f"ALTER TABLE {old} RENAME TO {new}")
            touched[0] += 1
            # 表已改名, 注意: SQLite 在 RENAME TABLE 时, 关联该表的索引如果是包含
            # 被改名列的 (如 idx_content_source 在 sources.id 上),
            # SQLite 会自动 DROP 它. 所以这部分"失踪"是预期行为.
            # 对列依赖的纯索引 (idx_content_published/fetched 等) 才需要手动重建.
            #
            # 我们只重建跟改名表的"普通索引列"相关的, 不重建已被 SQLite 合并的索引.
            for idx in idx_list:
                # 检测 idx 当前的隶属表
                cur = conn.execute(
                    "SELECT tbl_name FROM sqlite_master WHERE type='index' AND name=?",
                    (idx,)
                ).fetchone()
                if cur is None:
                    # 已被 SQLite 自动 DROP 了 (典型的 idx_*_source / FK_*) — 不需重建
                    # PRAGMA 索引在表上, PRIMARY KEY 自带唯一索引
                    print(f"  ⏭  索引 {idx} 已被 SQLite 自动处理 (典型: 跟随 RENAME 的索引)")
                    continue
                _rename_index(conn, idx, dry_run=False, touched=touched)
        _record_version(conn, version, desc)

    print(f"\n{'✅' if touched[0] > 0 else '⚠️ '} 完成: 改了 {touched[0]} 个 DDL")

    print(f"\n📋 迁移后 db 表:")
    for t in sorted([row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]):
        print(f"  - {t}")

    conn.close()
    return touched[0] > 0


if __name__ == "__main__":
    args = sys.argv[1:]
    apply = "--apply" in args
    db_path = next((a for a in args if not a.startswith("-")), None)

    if db_path is None:
        sys.path.insert(0, str(Path(__file__).parent))
        import config as _cfg
        db_path = str(_cfg.DB_PATH)
        print(f"(默认从 config.DB_PATH 读: {db_path})")
    print()
    migrate(db_path, apply=apply)
