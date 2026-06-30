# AI Agent Efficiency Coach Technical Architecture

版本：V0.1

目标：用最简单的 Python 单体架构实现 AI Agent 选题、总结、脚本生成工作台。

## 1. 技术原则

1. 优先本地可运行。
2. 优先少依赖、少组件。
3. 不做前后端分离。
4. 数据先进入 SQLite，后续再考虑升级。
5. 后台任务用 Python 自身能力实现。
6. 检索先用 SQL，数据量变大后升级 SQLite FTS5。
7. 每个关键事实保留来源，降低幻觉风险。

## 2. 推荐技术栈

| 模块 | 技术 |
|---|---|
| Web 框架 | FastAPI |
| HTML 模板 | Jinja2 |
| 页面交互 | HTMX + 少量原生 JavaScript |
| 样式 | 普通 CSS |
| 数据库 | SQLite |
| 数据访问 | sqlite3 或 SQLModel |
| 后台任务 | SQLite jobs 表 + Python worker thread |
| 定时任务 | APScheduler |
| 抓取 | requests、feedparser、trafilatura、BeautifulSoup、Playwright |
| LLM 调用 | OpenAI API 或可替换 provider |
| 配置 | .env + pydantic-settings |
| 日志 | Python logging |

## 3. 应用架构

```text
Browser
  |
  v
FastAPI Routes
  |
  +--> Jinja2 Templates
  |
  +--> Services
        |
        +--> Source Fetcher
        +--> Content Cleaner
        +--> Topic Generator
        +--> Scorer
        +--> Script Generator
        +--> Fact Checker
  |
  v
Repositories
  |
  v
SQLite
```

## 4. 项目结构

```text
agent_script_radar/
├── app.py
├── config.py
├── requirements.txt
├── data/
│   └── app.sqlite
├── migrations/
│   └── 001_init.sql
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   ├── sources.html
│   ├── articles.html
│   ├── topics.html
│   ├── topic_detail.html
│   ├── settings.html
│   └── script_editor.html
├── static/
│   ├── app.css
│   └── app.js
├── repositories/
│   ├── db.py
│   ├── sources_repo.py
│   ├── articles_repo.py
│   ├── topics_repo.py
│   ├── scripts_repo.py
│   ├── settings_repo.py
│   └── jobs_repo.py
├── services/
│   ├── crawler.py
│   ├── cleaner.py
│   ├── llm.py
│   ├── summarizer.py
│   ├── topic_generator.py
│   ├── scorer.py
│   ├── script_generator.py
│   └── fact_checker.py
├── workers/
│   ├── scheduler.py
│   └── job_runner.py
└── prompts/
    ├── content_card.md
    ├── topic_score.md
    ├── script_douyin.md
    ├── script_xiaohongshu.md
    └── fact_check.md
```

## 5. 数据模型

### 5.1 sources

信息源表。

```sql
CREATE TABLE sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  type TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT 'B',
  keywords TEXT,
  config_json TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  fetch_interval_minutes INTEGER NOT NULL DEFAULT 1440,
  last_cursor TEXT,
  last_seen_item_id TEXT,
  last_fetched_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

type 可选值：

```text
rss
webpage
github
arxiv
manual
```

level 可选值：

```text
S
A
B
C
```

config_json 用于保存不同来源类型的差异化配置，例如 GitHub query、arXiv 分类、排序方式、分页大小、是否需要 Playwright 等。last_cursor 和 last_seen_item_id 用于增量抓取，避免每次从头扫描。

### 5.2 articles

原始内容表。

```sql
CREATE TABLE articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER,
  source_item_id TEXT,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  canonical_url TEXT,
  author TEXT,
  published_at TEXT,
  raw_html TEXT,
  content_text TEXT,
  summary TEXT,
  key_points TEXT,
  content_hash TEXT NOT NULL,
  language TEXT,
  fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processed_at TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE UNIQUE INDEX idx_articles_content_hash ON articles(content_hash);
CREATE UNIQUE INDEX idx_articles_source_item ON articles(source_id, source_item_id)
  WHERE source_item_id IS NOT NULL;
CREATE UNIQUE INDEX idx_articles_canonical_url ON articles(canonical_url)
  WHERE canonical_url IS NOT NULL;
CREATE INDEX idx_articles_published_at ON articles(published_at);
CREATE INDEX idx_articles_source_id ON articles(source_id);
```

status 可选值：

```text
new
processed
ignored
failed
```

summary 和 key_points 保存文章级摘要，供选题生成、排查和重新聚合复用。processed_at 表示文章完成摘要或处理的时间。

### 5.3 topics

选题表。

```sql
CREATE TABLE topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  one_line_takeaway TEXT,
  summary TEXT,
  category TEXT,
  audience TEXT,
  recommended_column TEXT,
  recommended_platform TEXT,
  recommended_duration INTEGER,
  score INTEGER NOT NULL DEFAULT 0,
  source_level TEXT,
  actionable_value TEXT,
  risk_notes TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_topics_score ON topics(score);
CREATE INDEX idx_topics_status ON topics(status);
```

status 可选值：

```text
new
selected
scripted
archived
```

### 5.4 topic_articles

选题与文章关联表。

```sql
CREATE TABLE topic_articles (
  topic_id INTEGER NOT NULL,
  article_id INTEGER NOT NULL,
  PRIMARY KEY (topic_id, article_id),
  FOREIGN KEY (topic_id) REFERENCES topics(id),
  FOREIGN KEY (article_id) REFERENCES articles(id)
);
```

### 5.5 topic_facts

关键事实表。

```sql
CREATE TABLE topic_facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_id INTEGER NOT NULL,
  claim TEXT NOT NULL,
  source_url TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'medium',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (topic_id) REFERENCES topics(id)
);
```

confidence 可选值：

```text
high
medium
low
```

### 5.6 scripts

脚本表。

```sql
CREATE TABLE scripts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_id INTEGER NOT NULL,
  platform TEXT NOT NULL,
  format TEXT NOT NULL,
  duration INTEGER NOT NULL,
  title TEXT,
  hook TEXT,
  body TEXT NOT NULL,
  cta TEXT,
  cover_text TEXT,
  description TEXT,
  hashtags TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (topic_id) REFERENCES topics(id)
);

CREATE INDEX idx_scripts_topic_id ON scripts(topic_id);
CREATE UNIQUE INDEX idx_scripts_version ON scripts(topic_id, platform, format, duration, version);
```

同一 topic、platform、format、duration 下，每次重新生成脚本时 version 递增，保留历史版本。

### 5.7 creator_profile

账号人设配置表。

```sql
CREATE TABLE creator_profile (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  positioning TEXT NOT NULL,
  target_audience TEXT,
  tone TEXT,
  content_boundary TEXT,
  default_cta TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

默认值：

```text
name: AI效率教练
positioning: 把复杂 AI Agent 技术拆成普通人也能跑通的效率工作流
target_audience: 内容创作者、知识博主、独立开发者、小团队老板、AI工具新手
tone: 直接、实用、教练式、有步骤感
content_boundary: 不做空泛新闻，不做参数堆砌，不制造焦虑
default_cta: 关注我，我会继续把复杂 AI Agent 技术拆成你能直接用的效率工作流
```

creator_profile 必须通过设置页可编辑。代码只能使用默认值做首次初始化，不允许在 prompt 或 service 中硬编码“AI效率教练”。

### 5.8 llm_settings

模型配置表。

```sql
CREATE TABLE llm_settings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL DEFAULT 'openai',
  model TEXT NOT NULL,
  temperature REAL NOT NULL DEFAULT 0.4,
  max_tokens INTEGER NOT NULL DEFAULT 2000,
  api_key_env_var TEXT NOT NULL DEFAULT 'OPENAI_API_KEY',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

说明：

1. 页面允许修改 provider、model、temperature、max_tokens。
2. API Key 仍放在 .env 中，页面只保存 api_key_env_var，不保存密钥明文。
3. 应用首次启动时使用 .env 中的 DEFAULT_LLM_PROVIDER 和 DEFAULT_LLM_MODEL 初始化一条配置。
4. 所有 LLM 调用都必须读取 llm_settings 当前配置。

### 5.9 jobs

后台任务表。

```sql
CREATE TABLE jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  payload_json TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  locked_by TEXT,
  heartbeat_at TEXT,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TEXT,
  finished_at TEXT
);

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_type ON jobs(type);
CREATE INDEX idx_jobs_available_at ON jobs(available_at);
```

job type 可选值：

```text
fetch_source
fetch_all_sources
process_article
generate_topic
generate_script
fact_check_script
```

## 6. 后台任务设计

### 6.1 任务队列策略

不引入 Celery 和 Redis。使用 SQLite jobs 表作为持久化任务队列。

处理逻辑：

```text
1. Web 请求创建 pending job。
2. worker thread 每隔 1-3 秒查询 pending jobs。
3. 抢占一条任务，标记为 running。
4. 执行业务逻辑。
5. 成功则标记 done。
6. 失败则记录 error，attempts + 1。
7. attempts 小于 max_attempts 时可重新置为 pending。
```

抢占任务时只选择：

```text
status = pending
available_at <= now
```

任务运行时 worker 定期更新 heartbeat_at。若程序崩溃，启动时把超时的 running 任务恢复为 pending：

```text
status = running
heartbeat_at < now - timeout
```

locked_by 保存当前 worker 标识，方便排查任务卡住的问题。

### 6.2 并发策略

MVP 阶段默认单 worker，避免 SQLite 写锁问题。

后续可升级为：

1. 抓取任务 2-3 个并发。
2. LLM 任务 1 个并发。
3. 长任务增加取消按钮。

### 6.3 定时任务

APScheduler 负责创建任务，不直接执行业务。

示例：

```text
每天 09:00 创建 fetch_all_sources job
每天 09:30 创建 generate_topic job
```

## 7. 抓取设计

### 7.1 抓取策略

优先级：

1. RSS/API。
2. 静态网页抓取。
3. Playwright 动态抓取。
4. 手动录入。

### 7.2 去重策略

去重字段：

```text
canonical_url
content_hash
title + source_id
```

content_hash 生成方式：

```text
normalize(title + content_text[:5000]) -> sha256
```

canonical_url 优先来自页面 canonical link；若不存在，则使用规范化后的 url。source_item_id 优先使用 RSS guid、GitHub id、arXiv id、HN objectID 等来源侧稳定 ID。

### 7.3 内容清洗

清洗目标：

1. 提取正文。
2. 去除导航、广告、推荐阅读。
3. 保留标题、作者、发布时间、正文、代码片段、链接。
4. 标记语言。

### 7.4 选题聚合策略

MVP 阶段使用可解释规则聚合：

1. 时间窗口默认 7 天。
2. 命中同一关键词组的文章进入候选集合。
3. 标题核心名词重合时合并。
4. 同一集合内优先使用 S/A 级来源生成关键事实。
5. 支持用户在文章详情页手动加入已有 topic。

后续再考虑 FTS5 相似搜索或向量聚类。

## 8. LLM 流程

### 8.1 总体流程

```text
Article Text
  -> Article Summary
  -> Topic Card
  -> Score
  -> Script
  -> Fact Check
```

### 8.2 内容卡 Prompt 输入

```text
账号人设
模型配置
文章标题
文章来源
发布时间
正文摘要
关键段落
```

### 8.3 内容卡 Prompt 输出

要求输出 JSON：

```json
{
  "title": "...",
  "one_line_takeaway": "...",
  "summary": "...",
  "category": "...",
  "audience": ["..."],
  "recommended_column": "...",
  "recommended_platform": "...",
  "recommended_duration": 90,
  "actionable_value": "...",
  "risk_notes": "...",
  "key_facts": [
    {
      "claim": "...",
      "source_url": "..."
    }
  ]
}
```

### 8.4 脚本生成约束

脚本必须符合：

1. 第一 3 秒明确痛点或结果。
2. 包含一个常见错误。
3. 包含一个正确工作流。
4. 包含 4-6 个可执行步骤。
5. 包含一句可复制提示词。
6. 包含一个 “X 不是 Y” 的关键区分。
7. 包含风险提醒。
8. 结尾回到设置页配置的人设。

### 8.5 事实校验

事实校验不要求完全自动判断真伪，MVP 只做三件事：

1. 抽取脚本中的事实性声明。
2. 检查是否能在 topic_facts 或关联文章中找到来源。
3. 标记无来源或高风险表述。

输出示例：

```json
{
  "status": "needs_review",
  "issues": [
    {
      "claim": "MCP 已经成为所有 Agent 工具的统一标准",
      "problem": "过度概括，来源不足",
      "suggestion": "改为：MCP 正在成为连接 Agent 与外部系统的重要协议之一"
    }
  ]
}
```

## 9. 路由设计

### 9.1 页面路由

```text
GET  /                         首页
GET  /sources                  来源库
POST /sources                  新增来源
GET  /sources/{id}/edit        编辑来源页
POST /sources/{id}             更新来源
POST /sources/{id}/fetch       抓取单个来源

GET  /articles                 文章池
GET  /articles/{id}            文章详情
POST /articles/{id}/ignore     忽略文章

GET  /topics                   选题库
GET  /topics/{id}              选题详情
POST /topics/generate          生成选题
POST /topics/{id}/select       选中选题
POST /topics/{id}/archive      归档选题

GET  /topics/{id}/scripts      脚本编辑页
POST /topics/{id}/scripts      生成脚本
POST /scripts/{id}             保存脚本
POST /scripts/{id}/fact-check  校验脚本

GET  /settings                 设置页
POST /settings/profile         更新账号人设
POST /settings/model           更新模型配置

GET  /jobs                     任务列表
```

### 9.2 HTMX 局部刷新

适合用 HTMX 的位置：

1. 抓取按钮点击后刷新任务状态。
2. 选题卡状态切换。
3. 生成脚本后局部替换编辑区。
4. 任务列表自动刷新。

## 10. 检索设计

### 10.1 MVP SQL 检索

```sql
SELECT *
FROM articles
WHERE title LIKE '%' || :keyword || '%'
   OR content_text LIKE '%' || :keyword || '%'
ORDER BY published_at DESC
LIMIT 100;
```

### 10.2 后续 FTS5 升级

```sql
CREATE VIRTUAL TABLE articles_fts
USING fts5(title, content_text);
```

FTS5 仍在 SQLite 内部，不增加部署复杂度。

## 11. 配置设计

.env 示例：

```text
APP_ENV=development
APP_HOST=127.0.0.1
APP_PORT=8000
DATABASE_PATH=data/app.sqlite
OPENAI_API_KEY=
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=
FETCH_USER_AGENT=AgentScriptRadar/0.1
JOB_HEARTBEAT_TIMEOUT_SECONDS=300
```

说明：DEFAULT_LLM_PROVIDER 和 DEFAULT_LLM_MODEL 只用于首次初始化 llm_settings。应用运行后以页面保存的模型配置为准。

## 12. 错误处理

### 12.1 抓取错误

记录到 sources.last_error 和 jobs.error。

常见错误：

1. 连接失败。
2. 超时。
3. 解析失败。
4. 内容为空。
5. 反爬限制。

### 12.2 LLM 错误

处理方式：

1. 记录原始错误。
2. job attempts + 1。
3. 失败超过次数后标记 failed。
4. 页面允许手动重试。

### 12.3 JSON 解析错误

LLM 输出 JSON 失败时：

1. 尝试提取 JSON 片段。
2. 失败则要求模型修复 JSON。
3. 仍失败则记录 failed。

## 13. 安全与合规

1. 不保存用户敏感账号密码。
2. API Key 只放 .env，不入库。
3. 页面默认本地访问。
4. 对抓取内容保留来源链接。
5. 生成脚本时避免全文复刻原文。
6. 对不确定事实标记“需人工确认”。
7. 发布前保留人工编辑环节。

## 14. 本地运行方式

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

访问：

```text
http://127.0.0.1:8000
```

## 15. MVP 开发顺序

### Step 1: 项目骨架

1. FastAPI app。
2. Jinja2 base 模板。
3. SQLite 初始化。
4. 首页。

### Step 2: 来源库

1. sources 表。
2. 来源列表页。
3. 新增/编辑/停用来源。

### Step 3: 抓取与文章池

1. RSS 抓取。
2. 网页正文提取。
3. 去重。
4. 文章列表和详情。

### Step 4: 内容卡

1. LLM 封装。
2. 内容卡 prompt。
3. topics 和 topic_facts 入库。
4. 选题库页面。

### Step 5: 脚本生成

1. creator_profile 和 llm_settings 默认配置。
2. 脚本 prompt。
3. scripts 入库。
4. 脚本编辑页。

### Step 6: 任务系统

1. jobs 表。
2. worker thread。
3. 任务列表页。
4. APScheduler 定时创建任务。

### Step 7: 质量增强

1. 事实校验。
2. 发布素材包。
3. FTS5 搜索。
4. 视频表现反馈录入。

## 16. 后续可升级方向

当 MVP 跑通后，再考虑：

1. SQLite -> PostgreSQL。
2. SQL LIKE -> SQLite FTS5 -> 向量检索。
3. 单 worker -> 多 worker。
4. 本地应用 -> VPS 部署。
5. 手动发布 -> 半自动发布素材管理。
6. 单账号 -> 多账号人设配置。
