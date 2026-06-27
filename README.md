# 🧠 Info Digest — 信息精选系统

从海量信息中提取底层逻辑，每天早晚推送到飞书。

## 核心理念

> 海量内容 + 低质内容 = 浪费时间
> 让每一分钟的信息消费都有回报

不是新闻摘要——是**思维模型提取**。每条内容输出四层：

- ⚡ **底层逻辑** — 脱离原文能独立成立的原则
- 🧰 **思维模型** — "当你遇到X时，想想Y"
- 👉 **所以你应该** — 具体行动建议
- ⚔️ **反驳** — 这个观点可能错在哪

## 架构

```
采集层 (collector.py)
  RSS / RSSHub / Scrape / API / Manual
        ↓
AI 处理层 (processor.py)
  Stage 1: 快速过滤（淘汰50%低质内容）
  Stage 2: 底层逻辑提取（思维模型+行动建议+反驳）
        ↓
聚类层 (cluster.py)
  词汇重叠相似度，合并同类内容
        ↓
Digest 生成 (digest_builder.py)
  去重 + 排序 + 格式化
        ↓
推送层 (delivery.py)
  飞书 API 直推（不依赖 gateway）
```

## 信息源

| 源 | 类型 | 说明 |
|----|------|------|
| 段永平雪球 | 手动 | 投资/商业哲学 |
| Paul Graham | Scrape | 创业/思考 |
| Stratechery | RSS | 科技战略 |
| Wait But Why | RSS | 深度思考 |
| LessWrong | RSS | AI/理性主义 |
| Astral Codex Ten | RSS | 思考/理性 |
| Hacker News | API | 科技动态 |
| Marginal Revolution | RSS | 经济/文化 |
| The Diff | RSS | 投资/策略 |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行完整流程
python main.py

# 只采集
python main.py collect

# 只 AI 处理
python main.py process

# 全部重新处理
python main.py reprocess

# 测试（不推送）
python main.py test
```

## 配置

编辑 `config.py`：

```python
# 飞书
FEISHU_APP_ID = "your_app_id"
FEISHU_CHAT_ID = "your_chat_id"

# AI
XIAOMI_API_BASE = "https://token-plan-cn.xiaomimimo.com/v1"
XIAOMI_MODEL = "mimo-v2.5-pro"

# Digest
DIGEST_MAX_ITEMS = 8
QUALITY_THRESHOLD = 5.0
```

API Key 从 `~/.hermes/.env` 自动读取（`XIAOMI_API_KEY`）。

## 定时运行

已配置 Windows Scheduled Task：
- `InfoDigest-Morning` — 每天 09:00
- `InfoDigest-Evening` — 每天 18:00

或手动：`python main.py`

## 自定义信息源

在 `sources/` 目录下添加 markdown 文件，每条内容用 `---` 分隔：

```markdown
标题1
内容正文...

---

标题2
内容正文...
```

然后在数据库的 `sources` 表中添加记录，`fetch_method` 设为 `manual`。

## 文件结构

```
info-digest/
├── config.py          # 配置
├── db.py              # 数据库操作
├── collector.py       # 采集层
├── processor.py       # AI 处理（两阶段）
├── cluster.py         # 话题聚类
├── digest_builder.py  # Digest 生成
├── delivery.py        # 飞书推送
├── main.py            # 主流程编排
├── schema.sql         # 数据库 schema
├── run.bat            # Windows 定时任务入口
├── requirements.txt   # Python 依赖
├── UPGRADE_PLAN.md    # 升级方案
└── sources/           # 手动内容源
```

## License

MIT
