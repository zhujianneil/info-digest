# 信息精选系统 v2.0 升级方案

## 当前 v1.0 诊断

| 指标 | 现状 | 问题 |
|------|------|------|
| 信息源 | 12个，仅4个能跑 | 67% 失败率，中文源全挂 |
| 采集量 | 42条/次 | 仅 HN + 3个英文 RSS |
| AI 处理 | 逐条调 API，~15s/条 | 42条要10分钟，经常超时 |
| 摘要质量 | 洞见有了，但经常模板化 | "一句话30字内" 被当正文输出 |
| 去重 | 标题级 | 同一事件不同媒体报道不去重 |
| 反馈 | 未实现 | 无法学习偏好 |
| 推送 | 纯飞书文本 | 无卡片、无交互按钮 |
| 分类 | 科技占50% | 偏科严重 |

---

## 升级路线（4个阶段）

### Phase 1: 补血 — 修复采集层（1-2天）

**目标：信息源从4个可用 → 12个可用**

#### 1.1 修复 RSS 源
```
失败源及原因：
- Paul Graham: RSS URL 已失效（aaronsw.com 的旧 feed）
  → 换成 https://paulgraham.com/rss.html 或直接 scrape paulgraham.com/articles.html
- a16z: XML 不规范（含非法字符）
  → 用 requests 拿原始 XML，手动用 lxml 解析而非 feedparser
- Collaborative Fund: XML mismatched tag
  → 同上，手动修复 XML 后再 parse
- 经济学人: RSS 需要付费/被墙
  → 换成免费的 https://www.economist.com/briefing/rss 或用第三方镜像
- NFX Blog: XML 解析失败
  → 检查实际 RSS URL 是否变更
```

#### 1.2 修复中文源
```
- 段永平雪球: 需要登录态 cookie
  → 方案A: 用 Selenium/Playwright 模拟浏览器拿 cookie
  → 方案B: 用雪球 mobile API（需要 device_id + cookie）
  → 方案C: 转用 RSSHub（rsshub.app/xueqiu/user/1247347556）

- 张一鸣: 无公开 API
  → 手动维护一个 markdown 文件，定期从公开演讲/访谈中整理
  → 或用 RSSHub 监控包含"张一鸣"的新闻

- 王兴饭否: 饭否已关
  → 转用 RSSHub 监控相关报道
  → 或维护手动整理的内部发言集
```

#### 1.3 新增高质量源
```
Tier 1 候选：
- Ribbonfarm (Venkatesh Rao) — 系统思维   RSS: ribbonfarm.com/feed
- Slate Star Codex / Astral Codex Ten — 理性主义  RSS: astralcodexten.substack.com/feed
- Bored Elon Musk — 科技幽默+洞察  (Twitter/X 需要 RSSHub)
- 任正非内部讲话 — 华为心声社区  (scrape)
- Naval Ravikant — 投资/哲学  (Twitter + 博客)

Tier 2 候选：
- The Diff (Byrne Hobart) — 投资/策略
- Marginal Revolution (Tyler Cowen) — 经济/文化
- Kevin Simler (Melting Asphalt) — 人类行为
-.ribbonfarm — 系统思维
```

---

### Phase 2: 造血 — AI 处理升级（2-3天）

**目标：处理速度 10x，质量稳定**

#### 2.1 批量处理替代逐条调用
```
当前：42条 × 15s/条 = 10.5分钟
升级：3条/批 × 20s/批 = 5分钟（提速 2x）

方案：一次发 3 条内容给 LLM，要求输出 JSON 数组
减少 HTTP 开销 + 利用模型并行处理能力
```

#### 2.2 两阶段处理流水线
```
Stage 1: 快速过滤（轻量 prompt，<5s/条）
  → 输入：标题 + 前200字
  → 输出：reject/accept + 初步评分
  → 目的：快速淘汰 60% 低质内容

Stage 2: 深度分析（完整 prompt，仅处理 accept 的）
  → 输入：全文
  → 输出：完整摘要（洞见/金句/意义/新意）
  → 目的：对值得读的内容做深度加工
```

#### 2.3 增量处理 + 缓存
```
- 只处理新增内容（fetched_at > last_processed_at）
- 对已处理内容定期重评估（内容可能过时）
- 缓存 API 响应，相同内容不重复调用
```

#### 2.4 鲁棒性提升
```
- JSON 解析：用 regex fallback（已做）+ 重试机制
- 超时处理：指数退避重试（3次）
- 模型降级：MiMo 超时时 fallback 到 Hermes CLI
- 速率限制：每秒最多 2 个 API 调用
```

---

### Phase 3: 进化 — 智能化（3-5天）

**目标：从"搬运工"变成"编辑"**

#### 3.1 话题聚类（Topic Clustering）
```
问题：同一事件（如"GPT-5.6 发布"）可能有 3-4 条不同来源的报道
方案：
  1. 对每条内容生成 embedding（用 MiMo 或本地模型）
  2. 计算余弦相似度
  3. 相似度 > 0.8 的内容合并为一个话题
  4. 话题内的内容取最高质量的作为主条目，其他作为"延伸阅读"
效果：42条内容 → 可能聚类成 15-20 个独立话题
```

#### 3.2 偏好学习
```
数据源：
- 飞书消息按钮反馈（👍/👎）
- 用户主动说"这条好/这条没用"
- 用户点击原文链接的频率

模型：
- 简单版：统计各 category/source 的平均反馈分
- 进阶版：用 feedback 训练一个排序模型（content → predicted_score）
- 实时调整：近期反馈权重 > 历史反馈
```

#### 3.3 时效性感知
```
- 紧急新闻（如政策变化、重大事件）→ 立即推送，不等定时
- 常规内容 → 正常 digest
- 长期价值内容（如深度分析）→ 可以攒到周末推送"深度阅读"版
```

#### 3.4 中文内容增强
```
- 英文内容先翻译核心段落再摘要
- 中文源（雪球、任正非等）单独处理管道
- 混合语言 prompt：用中文输出摘要，保留英文关键术语
```

---

### Phase 4: 变现 — 产品化（5-7天）

**目标：从工具变成产品**

#### 4.1 飞书卡片消息
```
当前：纯文本 post
升级：Interactive Card（飞书消息卡片）
- 每条内容一个卡片块
- 带 👍/👎 按钮（回调到 webhook）
- 带"阅读全文"按钮
- 带"跳过"按钮
- 底部统计：今日几条必读、几条推荐
```

#### 4.2 Web Dashboard
```
- Flask/FastAPI 简单 web 界面
- 功能：
  - 浏览所有采集内容
  - 手动调整质量评分
  - 管理信息源（增删改）
  - 查看历史 Digest
  - 反馈统计仪表盘
- 技术：SQLite + Jinja2 模板（轻量）
```

#### 4.3 多渠道推送
```
- 飞书（已有）
- 邮件（SMTP，适合长文）
- Telegram（如果用户有）
- Webhook（供其他系统消费）
```

#### 4.4 周报/月报
```
- 每周日：本周 Top 10 必读 + 趋势分析
- 每月 1 号：月度信息消费报告
  - 读了多少条
  - 哪个领域最多
  - 质量趋势
  - 信息源健康度
```

---

## 技术债清理

| 项目 | 现状 | 修复 |
|------|------|------|
| JSON 解析 | regex fallback | 统一用 json5 或自定义 parser |
| 错误处理 | bare except | 分类处理（网络/解析/限流） |
| 日志 | print() | 换 logging 模块 + 文件输出 |
| 配置 | 硬编码 | 换 YAML 配置文件 |
| 测试 | 无 | 核心模块 pytest |
| 依赖管理 | requirements.txt | pyproject.toml + venv |

---

## 推荐执行顺序

```
Week 1: Phase 1（补血）+ Phase 2.1-2.2（批量处理）
  → 效果：12个源全通，处理速度 10x

Week 2: Phase 2.3-2.4（缓存+鲁棒）+ Phase 3.1（话题聚类）
  → 效果：增量处理，去重，digest 不重复

Week 3: Phase 3.2-3.4（偏好+时效+中文）+ Phase 4.1（飞书卡片）
  → 效果：个性化，推送体验升级

Week 4: Phase 4.2-4.4（Dashboard+多渠道+周报）
  → 效果：产品化
```

---

## 核心指标（v2.0 目标）

| 指标 | v1.0 | v2.0 目标 |
|------|------|----------|
| 可用信息源 | 4/12 (33%) | 12/12 (100%) |
| 日采集量 | 42条 | 100+条 |
| 处理速度 | 15s/条 | <3s/条 |
| 话题去重 | 无 | 80%+ 合并率 |
| Digest 质量 | 6.5/10 均分 | 7.5/10 均分 |
| 用户反馈 | 0 | 每日 3+ 条 |
| 推送渠道 | 1 (飞书) | 3 (飞书+邮件+web) |
