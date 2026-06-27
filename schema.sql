-- 信息精选系统 v1
-- 理念：让每一分钟的信息消费都有回报

-- ============================================================
-- 1. 信息源
-- ============================================================
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,                    -- 段永平雪球、张一鸣播客...
    url         TEXT,                             -- 主页/RSS地址
    tier        INTEGER NOT NULL DEFAULT 1,       -- 1=核心源, 2=扩展源
    type        TEXT,                             -- 投资/产品/行业洞察...
    platform    TEXT,                             -- xueqiu/rss/youtube/blog
    fetch_method TEXT NOT NULL DEFAULT 'rss',     -- rss/api/scrape
    fetch_config TEXT,                            -- JSON: 抓取参数
    enabled     INTEGER NOT NULL DEFAULT 1,
    last_fetched_at TEXT,                         -- ISO时间
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(name)
);

-- ============================================================
-- 2. 原始内容
-- ============================================================
CREATE TABLE IF NOT EXISTS content (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   INTEGER NOT NULL REFERENCES sources(id),
    external_id TEXT,                             -- 原平台唯一ID（防重）
    title       TEXT,
    url         TEXT,                             -- 原文链接
    author      TEXT,
    content     TEXT,                             -- 原始全文/摘要
    content_type TEXT NOT NULL DEFAULT 'text',    -- text/video/podcast/image
    published_at TEXT,                            -- 原文发布时间
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
    word_count  INTEGER DEFAULT 0,
    language    TEXT DEFAULT 'zh',
    tags        TEXT,                             -- JSON数组
    UNIQUE(source_id, external_id)
);

-- ============================================================
-- 3. AI 处理结果
-- ============================================================
CREATE TABLE IF NOT EXISTS summaries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id  INTEGER NOT NULL REFERENCES content(id),
    model       TEXT,                             -- 用了哪个模型
    -- 核心输出
    one_liner   TEXT NOT NULL,                    -- 一句话概括（30字内）
    key_points  TEXT NOT NULL,                    -- 核心要点 JSON数组
    insight     TEXT,                             -- AI提取的洞察/金句
    category    TEXT,                             -- 投资/产品/管理/行业/科技
    quality_score REAL DEFAULT 0,                 -- 质量评分 0-10
    -- 元数据
    tokens_used INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(content_id)
);

-- ============================================================
-- 4. 每日Digest
-- ============================================================
CREATE TABLE IF NOT EXISTS digests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_date TEXT NOT NULL,                    -- YYYY-MM-DD
    period      TEXT NOT NULL,                    -- morning / evening
    title       TEXT,                             -- Digest标题
    body        TEXT,                             -- 完整Digest文本（Markdown）
    item_count  INTEGER DEFAULT 0,                -- 包含几条
    sent_at     TEXT,                             -- 实际推送时间
    channel     TEXT DEFAULT 'feishu',            -- 推送渠道
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(digest_date, period)
);

-- ============================================================
-- 5. Digest 包含的内容条目
-- ============================================================
CREATE TABLE IF NOT EXISTS digest_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_id   INTEGER NOT NULL REFERENCES digests(id),
    summary_id  INTEGER NOT NULL REFERENCES summaries(id),
    position    INTEGER NOT NULL DEFAULT 0,       -- 排序位置
    included    INTEGER NOT NULL DEFAULT 1,       -- 是否最终入选
    reason      TEXT,                             -- 为什么选/不选
    UNIQUE(digest_id, summary_id)
);

-- ============================================================
-- 6. 用户反馈
-- ============================================================
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id  INTEGER NOT NULL REFERENCES content(id),
    rating      INTEGER NOT NULL,                 -- 1=有用, -1=无用, 0=跳过
    comment     TEXT,                             -- 可选备注
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(content_id)                            -- 每条内容只评一次（可更新）
);

-- ============================================================
-- 索引
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_content_source ON content(source_id);
CREATE INDEX IF NOT EXISTS idx_content_published ON content(published_at);
CREATE INDEX IF NOT EXISTS idx_content_fetched ON content(fetched_at);
CREATE INDEX IF NOT EXISTS idx_summaries_quality ON summaries(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_summaries_category ON summaries(category);
CREATE INDEX IF NOT EXISTS idx_digests_date ON digests(digest_date);
CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating);
