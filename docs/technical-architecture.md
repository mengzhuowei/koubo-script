# AI Agent Efficiency Coach Technical Architecture

版本：V0.3

目标：用 Python 单体架构实现 AI Agent 选题、总结、脚本、发布素材包生成工作台。

## 1. 技术原则

1. 优先本地可运行。
2. 优先少依赖、少组件。
3. 不做前后端分离。
4. 数据存入 MySQL；应用可通过 Docker 启动，MySQL 由宿主机或外部服务提供。
5. 后台任务用 Python 自身能力实现。
6. 文章检索使用 MySQL FULLTEXT/ngram；后续可升级向量检索或语义聚类。
7. 每个关键事实保留来源，降低幻觉风险。

## 2. 推荐技术栈

| 模块 | 技术 |
|---|---|
| Web 框架 | FastAPI |
| HTML 模板 | Jinja2 |
| 页面交互 | HTMX + 少量原生 JavaScript |
| 样式 | 普通 CSS |
| 数据库 | MySQL 8.0 |
| 数据访问 | pymysql + DictCursor |
| 后台任务 | MySQL jobs 表 + ThreadPoolExecutor(max_workers=3) |
| 定时任务 | APScheduler（抓取调度默认开启，选题调度默认关闭） |
| 抓取 | requests、feedparser、BeautifulSoup、lxml（trafilatura 作为依赖预留） |
| LLM 调用 | OpenAI API 或可替换 provider |
| 联网搜索 | Tavily API（可选，本地资料不足时联网补充） |
| 配置 | .env + pydantic-settings |
| 容器化 | Docker + docker-compose（app + mysql 双容器编排） |
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
        +--> Summarizer
        +--> Topic Generator
        +--> Scorer
        +--> Research Card Generator
        +--> Web Search
        +--> Fact Checker
        +--> Credibility Scorer
        +--> Script Generator
        +--> Assets Generator
        +--> Scheduler
  |
  v
Repositories
  |
  v
MySQL 8.0
```

## 4. 项目结构

```text
agent_script_radar/
├── app.py
├── config.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml        # app + mysql 双容器编排（不入库，本地化配置）
├── .dockerignore
├── .env.example
├── migrations/
│   ├── 001_init.sql          # MySQL 8.0 初始化 schema
│   ├── 002_fulltext.sql      # articles FULLTEXT/ngram 索引
│   ├── 003_script_assets.sql # 发布素材包表
│   ├── 004_research_cards.sql # 选题资料卡 + 来源表 + scripts.research_card_id
│   └── 005_web_search_usage.sql # 联网搜索预算追踪表
├── scripts/
│   └── seed_sources.py
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   ├── sources.html
│   ├── source_form.html
│   ├── articles.html
│   ├── article_detail.html
│   ├── topics.html
│   ├── topic_detail.html
│   ├── settings.html
│   ├── script_editor.html
│   ├── script_compare.html
│   ├── fact_check.html
│   ├── jobs.html
│   └── jobs_table.html
├── static/
│   ├── app.css
│   └── app.js
├── repositories/
│   ├── db.py                 # pymysql 连接 + _Conn 包装器 + migration 执行
│   ├── sources_repo.py
│   ├── articles_repo.py
│   ├── topics_repo.py
│   ├── scripts_repo.py
│   ├── assets_repo.py
│   ├── research_cards_repo.py  # 选题资料卡 + 来源表
│   ├── web_search_repo.py    # 联网搜索预算追踪
│   ├── settings_repo.py
│   └── jobs_repo.py
├── services/
│   ├── crawler.py
│   ├── cleaner.py
│   ├── llm.py
│   ├── summarizer.py
│   ├── topic_generator.py
│   ├── scorer.py
│   ├── research_card_generator.py # 选题资料卡生成
│   ├── web_search.py         # 联网搜索（Tavily provider）
│   ├── fact_checker.py       # 事实校验
│   ├── credibility_scorer.py # 来源可信度评分
│   ├── source_classifier.py  # 来源分类
│   ├── script_generator.py
│   └── assets_generator.py
├── workers/
│   ├── scheduler.py
│   └── job_runner.py
└── prompts/
    ├── content_card.md
    ├── topic_score.md
    ├── script_koubo.md
    ├── assets.md
    └── topic_research_card.md
```

## 5. 数据模型

### 5.1 sources

信息源表。

```sql
CREATE TABLE sources (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  url VARCHAR(1024) NOT NULL,
  type VARCHAR(32) NOT NULL,
  level VARCHAR(8) NOT NULL DEFAULT 'B',
  keywords VARCHAR(512),
  config_json TEXT,
  enabled TINYINT NOT NULL DEFAULT 1,
  fetch_interval_minutes INT NOT NULL DEFAULT 1440,
  last_cursor VARCHAR(255),
  last_seen_item_id VARCHAR(255),
  last_fetched_at DATETIME,
  last_error TEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

type 可选值：

```text
rss
webpage
webpage_list
spa_list
github_topics
bilibili_search
manual
```

level 可选值：

```text
S
A
B
C
```

config_json 用于保存不同来源类型的差异化配置。当前抓取服务支持 7 种类型：RSS（feedparser 解析）、单网页（trafilatura 提取正文）、列表型网页（先抓列表页提取文章链接再逐篇抓正文，限制最多 30 篇）、SPA 列表（动态渲染站点）、GitHub Topics（从 topics 列表页 `<article>` 卡片提取 repo 信息）、B 站搜索、手动录入。last_cursor 和 last_seen_item_id 用于后续增量抓取，避免每次从头扫描。

### 5.2 articles

原始内容表。

```sql
CREATE TABLE articles (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  source_id INT,
  source_item_id VARCHAR(512),
  title VARCHAR(1024) NOT NULL,
  url VARCHAR(1024) NOT NULL,
  canonical_url VARCHAR(1024),
  author VARCHAR(255),
  published_at DATETIME,
  raw_html LONGTEXT,
  content_text LONGTEXT,
  summary MEDIUMTEXT,
  key_points MEDIUMTEXT,
  content_hash VARCHAR(64) NOT NULL,
  language VARCHAR(16),
  fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processed_at DATETIME,
  status VARCHAR(16) NOT NULL DEFAULT 'new',
  CONSTRAINT fk_articles_source FOREIGN KEY (source_id) REFERENCES sources(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE UNIQUE INDEX idx_articles_content_hash ON articles(content_hash);
-- MySQL 不支持部分索引 WHERE，但唯一索引中多个 NULL 视为不同值，天然等价于部分索引效果
CREATE UNIQUE INDEX idx_articles_source_item ON articles(source_id, source_item_id);
-- utf8mb4 下 VARCHAR(1024) 索引达 4096 字节超过 3072 限制，使用前缀 768 字符（=3072 字节）
CREATE UNIQUE INDEX idx_articles_canonical_url ON articles(canonical_url(768));
CREATE INDEX idx_articles_published_at ON articles(published_at);
CREATE INDEX idx_articles_source_id ON articles(source_id);
CREATE INDEX idx_articles_status ON articles(status);
```

status 可选值：

```text
new          # 初始状态
processing   # 锁定处理中
processed    # 处理完成
ignored      # 忽略
```

状态流转：

```text
new -> processing（list_unprocessed_articles 用 UPDATE...LIMIT 原子锁定时写入 processed_at）
   -> processed（mark_processed 成功，processed_at 刷新为完成时间）
   -> new（revert_to_new 失败回滚，或 reset_stale_processing 超时回收）
```

summary 和 key_points 保存文章级摘要，供选题生成、排查和重新聚合复用。processed_at 具有双重语义：在 `list_unprocessed_articles` 锁定时写入 CURRENT_TIMESTAMP 作为"开始处理时间"，在 `mark_processed` 完成时刷新为"完成时间"。`reset_stale_processing` 用 processed_at 判定超时（默认 >10 分钟），兼容 NULL（旧残留数据），将超时的 processing 状态文章回滚为 new。

### 5.3 topics

选题表。

```sql
CREATE TABLE topics (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(512) NOT NULL,
  one_line_takeaway VARCHAR(1024),
  summary MEDIUMTEXT,
  category VARCHAR(64),
  audience TEXT,
  recommended_column VARCHAR(64),
  recommended_platform VARCHAR(32),
  recommended_duration INT,
  score INT NOT NULL DEFAULT 0,
  source_level VARCHAR(8),
  actionable_value TEXT,
  risk_notes TEXT,
  status VARCHAR(16) NOT NULL DEFAULT 'new',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

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
  topic_id INT NOT NULL,
  article_id INT NOT NULL,
  PRIMARY KEY (topic_id, article_id),
  CONSTRAINT fk_ta_topic FOREIGN KEY (topic_id) REFERENCES topics(id),
  CONSTRAINT fk_ta_article FOREIGN KEY (article_id) REFERENCES articles(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 5.5 topic_facts

关键事实表。

```sql
CREATE TABLE topic_facts (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  topic_id INT NOT NULL,
  claim TEXT NOT NULL,
  source_url VARCHAR(1024) NOT NULL,
  confidence VARCHAR(16) NOT NULL DEFAULT 'medium',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_facts_topic FOREIGN KEY (topic_id) REFERENCES topics(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_topic_facts_topic_id ON topic_facts(topic_id);
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
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  topic_id INT NOT NULL,
  platform VARCHAR(32) NOT NULL,
  format VARCHAR(32) NOT NULL,
  duration INT NOT NULL,
  title VARCHAR(512),
  hook VARCHAR(1024),
  body LONGTEXT NOT NULL,
  cta VARCHAR(1024),
  cover_text VARCHAR(255),
  description MEDIUMTEXT,
  hashtags TEXT,
  research_card_id INT NULL,  -- 004 新增，记录脚本使用了哪一份资料卡
  version INT NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_scripts_topic FOREIGN KEY (topic_id) REFERENCES topics(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_scripts_topic_id ON scripts(topic_id);
CREATE UNIQUE INDEX idx_scripts_version ON scripts(topic_id, platform, format, duration, version);
```

同一 topic、platform、format、duration 下，每次重新生成脚本时 version 递增，保留历史版本。

### 5.7 script_assets

发布素材包表。每个脚本最多一条素材记录，重新生成时覆盖。

```sql
CREATE TABLE script_assets (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  script_id INT NOT NULL,
  titles TEXT,
  cover_texts TEXT,
  description MEDIUMTEXT,
  hashtags TEXT,
  comment_questions TEXT,
  pinned_comment VARCHAR(1024),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_assets_script FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE,
  UNIQUE KEY uk_assets_script (script_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

字段说明：

1. titles、cover_texts、hashtags、comment_questions 使用 JSON 字符串保存数组。
2. description 保存发布简介。
3. pinned_comment 保存置顶评论。
4. 生成素材包为手动触发的 LLM 任务，不自动发布到平台。

### 5.8 creator_profile

账号人设配置表。

```sql
CREATE TABLE creator_profile (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(64) NOT NULL,
  positioning VARCHAR(512) NOT NULL,
  target_audience VARCHAR(512),
  tone VARCHAR(255),
  content_boundary VARCHAR(512),
  default_cta VARCHAR(512),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
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

### 5.9 llm_settings

模型配置表。

```sql
CREATE TABLE llm_settings (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  provider VARCHAR(32) NOT NULL DEFAULT 'openai',
  model VARCHAR(64) NOT NULL,
  temperature FLOAT NOT NULL DEFAULT 0.4,
  max_tokens INT NOT NULL DEFAULT 2000,
  api_key_env_var VARCHAR(64) NOT NULL DEFAULT 'OPENAI_API_KEY',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

说明：

1. 页面允许修改 provider、model、temperature、max_tokens。
2. API Key 仍放在 .env 中，页面只保存 api_key_env_var，不保存密钥明文。
3. 应用首次启动时使用 .env 中的 DEFAULT_LLM_PROVIDER 和 DEFAULT_LLM_MODEL 初始化一条配置。
4. 所有 LLM 调用都必须读取 llm_settings 当前配置。

### 5.10 jobs

后台任务表。

```sql
CREATE TABLE jobs (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  type VARCHAR(32) NOT NULL,
  payload_json TEXT,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 3,
  available_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  locked_by VARCHAR(64),
  heartbeat_at DATETIME,
  error TEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  started_at DATETIME,
  finished_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_type ON jobs(type);
CREATE INDEX idx_jobs_available_at ON jobs(available_at);
```

job type 可选值（job_runner.py `_dispatch` 支持 9 种）：

```text
fetch_source
fetch_all_sources
process_article
generate_topic
regenerate_topic_for_article
generate_research_card
refresh_research_card
generate_script
generate_assets
```

### 5.11 topic_research_cards

选题资料卡主表（004 migration）。资料卡是选题与脚本之间的中间产物，整理本地文章库相关资料供脚本生成引用。

```sql
CREATE TABLE topic_research_cards (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  topic_id INT NOT NULL,
  title VARCHAR(255) NOT NULL,
  summary MEDIUMTEXT,
  card_json MEDIUMTEXT NOT NULL,          -- 完整资料卡 JSON
  confidence VARCHAR(16) NOT NULL DEFAULT 'medium',
  local_source_count INT NOT NULL DEFAULT 0,
  web_source_count INT NOT NULL DEFAULT 0,
  has_official_source TINYINT NOT NULL DEFAULT 0,
  generated_by VARCHAR(64) NOT NULL DEFAULT 'llm',
  version INT NOT NULL DEFAULT 1,
  needs_refresh TINYINT NOT NULL DEFAULT 0, -- 标记需要刷新（来源变化时）
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_research_cards_topic FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_research_cards_topic_id ON topic_research_cards(topic_id);
```

字段说明：

1. card_json 用 TEXT 存 json.dumps 字符串，与现有表（audience/hashtags）保持一致。
2. local_source_count / web_source_count 分别记录本地文章与联网搜索来源数量。
3. has_official_source 标记是否包含官方来源（OpenAI/Anthropic 等）。
4. needs_refresh 用于标记资料卡需要刷新（如关联文章有新增时）。

### 5.12 topic_research_sources

资料卡来源表（004 migration），记录每张资料卡引用的来源（本地文章 / 联网搜索 / 手动添加）。

```sql
CREATE TABLE topic_research_sources (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  research_card_id INT NOT NULL,
  article_id INT,                          -- 本地来源时关联 articles.id
  source_url VARCHAR(1024) NOT NULL,
  source_title VARCHAR(512),
  source_name VARCHAR(255),
  source_level VARCHAR(8),
  published_at DATETIME,
  source_type VARCHAR(32) NOT NULL DEFAULT 'local',  -- local / web / manual
  excerpt MEDIUMTEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_research_sources_card FOREIGN KEY (research_card_id) REFERENCES topic_research_cards(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_research_sources_card_id ON topic_research_sources(research_card_id);
```

### 5.13 web_search_usage

联网搜索预算追踪表（005 migration）。每次联网搜索消耗记录一行，月度/单选题预算通过 SUM 聚合查询。

```sql
CREATE TABLE web_search_usage (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  topic_id INT NOT NULL,
  query_text VARCHAR(512) NOT NULL,
  credits_used INT NOT NULL DEFAULT 0,
  results_count INT NOT NULL DEFAULT 0,
  search_depth VARCHAR(16) NOT NULL DEFAULT 'basic',  -- basic / advanced
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_web_usage_topic FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_web_usage_topic_id ON web_search_usage(topic_id);
CREATE INDEX idx_web_usage_created_at ON web_search_usage(created_at);
```

## 6. 后台任务设计

### 6.1 任务队列策略

不引入 Celery 和 Redis。使用 MySQL jobs 表作为持久化任务队列。

处理逻辑：

```text
1. Web 请求创建 pending job。
2. worker 主线程每隔 2 秒（JOB_POLL_INTERVAL_SECONDS 可配）调用 claim_next_job 抢占一条 pending 任务。
3. 抢占成功后提交到 ThreadPoolExecutor 并发执行（最多 3 个任务同时运行）。
4. 执行业务逻辑。
5. 成功则标记 done。
6. 失败则记录 error，attempts + 1。
7. attempts 小于 max_attempts 时可重新置为 pending。
```

任务抢占使用 `claim_next_job`，内部用 `START TRANSACTION` + `SELECT ... FOR UPDATE SKIP LOCKED` 原子抢占一条任务：

```sql
START TRANSACTION;
SELECT * FROM jobs
  WHERE status = 'pending' AND available_at <= CURRENT_TIMESTAMP
  ORDER BY id ASC LIMIT 1
  FOR UPDATE SKIP LOCKED;
-- 找到后立即 UPDATE 为 running 并写入 locked_by / heartbeat_at
COMMIT;
```

`FOR UPDATE SKIP LOCKED` 让多个 worker 并发抢占时互不阻塞，被其他 worker 锁住的行直接跳过。

任务运行时 worker 写入 heartbeat_at。应用启动时会直接把所有 running 任务恢复为 pending，因为进程重启意味着旧 worker 已不存在：

```text
status = running
-> status = pending
```

locked_by 保存当前 worker 标识，方便排查任务卡住的问题。每个 handler 在独立线程中运行，DB 连接（get_conn）每次新建，天然线程安全，不存在共享状态竞争。

### 6.2 并发策略

已升级为 `ThreadPoolExecutor(max_workers=3)`，thread_name_prefix="job-worker"。

```text
单线程取任务（_loop 每 2 秒 claim_next_job）
  -> 提交到线程池并发执行（最多 3 个任务同时运行）
  -> 慢任务（如 LLM 调用）不会阻塞快任务（如抓取）
```

max_workers=3 是 DB 连接池/反爬压力与吞吐量的平衡点。MySQL 行级锁（FOR UPDATE SKIP LOCKED）为后续进一步扩容多 worker 留好基础。

### 6.3 定时任务

当前代码已接入 APScheduler。调度器只创建 job 入队，不直接执行业务，仍由 worker 消费。

已实现两类调度：

1. 到期来源抓取：默认开启。每隔 `SCHEDULER_FETCH_CHECK_INTERVAL_MINUTES` 分钟检查一次 `sources.last_fetched_at` 与 `fetch_interval_minutes`，为到期来源创建 `fetch_source` 任务。若该来源已有 pending/running 任务则跳过。
2. 自动生成选题：默认关闭。开启 `SCHEDULER_TOPIC_ENABLED=true` 后，按 `SCHEDULER_TOPIC_CRON` 创建 `generate_topic` 任务。该任务会消耗 LLM，因此默认不自动触发。

示例：

```text
每 30 分钟检查到期来源并创建 fetch_source job
可选：每天 09:30 创建 generate_topic job
```

## 7. 抓取设计

### 7.1 抓取策略

优先级：

1. RSS/API。
2. 静态网页抓取。
3. 列表型网页抓取（webpage_list：先抓列表页提取文章链接，再逐篇抓正文）。
4. SPA 列表抓取（spa_list：动态渲染站点）。
5. GitHub Topics 抓取（github_topics：从 topics 列表页 `<article>` 卡片提取 repo 信息，不回抓 repo 页）。
6. B 站搜索抓取（bilibili_search）。
7. 手动录入。

当前抓取服务（`crawler.py` 的 `fetch_source()`）支持 7 种来源类型：`rss` / `webpage` / `webpage_list` / `spa_list` / `github_topics` / `bilibili_search` / `manual`。type→函数映射在 `fetch_source()` 内用 if/elif 实现，非字典。`webpage_list` 内有局部常量 `_MAX_ARTICLES = 30`，限制列表页抓取篇数避免耗时过长。

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

`FetchItem` 增加 `fetch_error` 字段记录抓取失败原因（如"跳过回抓：源站已知反爬"、"熔断：同源连续多次回抓失败"、"回抓失败"）。正文为空时，`_handle_fetch_source` 用 fetch_error 生成提示文本入库，避免用户看到无信息的"无正文"。

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

后续再考虑向量聚类或更强语义相似度，用于跨来源选题聚合。

### 7.5 反爬策略

抓取服务实现三级反爬保护，避免被源站封禁：

1. **per-host throttling（每主机限速）**：同一 host 的请求间隔 ≥ 1.5 秒，避免短时间高频访问触发封禁。
2. **exponential backoff（指数退避重试）**：遇到 429 / 5xx 时按指数退避重试，避免被限流后立即重试加重封禁。
3. **circuit breaker（熔断）**：同一来源连续 5 次回抓失败后触发熔断，后续条目不再回抓原文，直接用短摘要入库。

其他反爬措施：

1. **浏览器 User-Agent**：必须使用浏览器 UA（默认 Chrome UA），避免被 SSR 站点（如 InfoQ）当作爬虫返回空壳 HTML。
2. **`_REFETCH_SKIP_HOSTS`**：已知反爬站点跳过回抓，直接保留 RSS 摘要入库。当前包含 `{openai.com, qbitai.com, huggingface.co, blog.google, research.google}`，匹配规则为精确匹配或子域名匹配（如 `research.openai.com` 命中 `openai.com`）。

## 8. LLM 流程

### 8.1 总体流程

```text
Article Text
  -> Article Summary
  -> Topic Card
  -> Score
  -> Script
  -> Assets Pack（手动触发）
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

脚本生成使用三模板独立叙事结构，每个模板对应不同的内容形态：

```text
热点解读 -> 新闻评论式
工具教程 -> 实操教学式
观点拆解 -> 辩论式
```

不同模板使用不同的叙事结构，不得混用同一套框架。

脚本必须符合：

1. 第一 3 秒明确痛点或结果。
2. 包含一个常见错误。
3. 包含一个正确工作流。
4. 包含 4-6 个可执行步骤。
5. 包含一句可复制提示词。
6. 包含一个 “X 不是 Y” 的关键区分。
7. 包含风险提醒。
8. 结尾回到设置页配置的人设。

其他约束：

1. **字数按 duration 动态计算**：目标字数 = `duration * 5 ~ duration * 7`（如 90 秒视频约 450-630 字）。生成后校验 body+hook+cta 总字数，低于或超过目标范围时记录 warning 告警。
2. **temperature=0.9**：脚本生成调用 LLM 时用 temperature=0.9 覆盖 DB 默认值（0.4），提升创意多样性。素材生成同样用 0.9，分析类任务用 DB 默认 0.4。
3. **render_prompt helper**：必须用 `render_prompt(template, **kwargs)` 渲染 prompt，替代 `str.format`，避免 prompt 中的 JSON 花括号与 format 占位符冲突。
4. **版本管理**：同一 (topic_id, platform, format, duration) 下每次重新生成 version 递增，保留历史版本，支持 restore 接口恢复历史版本。

### 8.5 发布素材包生成

素材包基于已保存脚本生成，手动触发，输出 JSON 后写入 script_assets。

输出字段：

```json
{
  "titles": ["标题1", "标题2", "标题3", "标题4", "标题5"],
  "cover_texts": ["封面1", "封面2", "封面3"],
  "description": "视频简介",
  "hashtags": ["标签1", "标签2"],
  "comment_questions": ["问题1", "问题2", "问题3"],
  "pinned_comment": "置顶评论"
}
```

### 8.6 事实校验（已实现）

事实校验由 `fact_checker.py` 实现，对脚本中的事实性声明进行核验，降低幻觉风险。

流程：

1. 从脚本 body 中抽取事实性声明（claim）。
2. 检查每条 claim 是否能在 `topic_facts` 或关联文章来源中找到支撑。
3. 标记无来源或高风险表述，给出修改建议。
4. 通过 `GET /scripts/{script_id}/fact-check` 路由触发并展示结果页面（fact_check.html）。

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

### 8.7 选题资料卡生成流程

选题资料卡由 `research_card_generator.py` 实现，是选题与脚本之间的中间产物，整理本地文章库相关资料供脚本生成引用。

流程：

```text
Topic + 关联文章
  -> 本地文章库 FULLTEXT 检索（按选题关键词/标题）
  -> 汇总检索到的文章摘要、关键事实、来源信息
  -> LLM 生成结构化资料卡 JSON（render_prompt 渲染 topic_research_card.md）
  -> 写入 topic_research_cards + topic_research_sources
  -> scripts.research_card_id 关联使用的资料卡
```

资料卡字段（card_json）：

1. summary：资料卡总览摘要。
2. key_facts：关键事实列表（含 claim + source_url）。
3. sources：来源列表（本地文章 + 联网搜索 + 手动添加）。
4. confidence：置信度（high / medium / low）。

资料卡支持刷新（refresh_research_card job）：关联文章有新增或 needs_refresh 标记为 1 时，重新生成资料卡并 version 递增。

### 8.8 联网搜索流程

联网搜索由 `web_search.py`（Tavily provider）实现，在本地文章库资料不足时按配置联网补充。

流程：

```text
生成资料卡时
  -> 评估本地来源数量是否充足
  -> 不足且 WEB_SEARCH_ENABLED=true 时
     -> 构造搜索 query（基于选题标题/关键词）
     -> 调用 Tavily Search API（basic/advanced 两种深度）
     -> 可选 Tavily Extract 提取正文（批量 URL）
     -> 结果写入 topic_research_sources（source_type='web'）
     -> 消耗记录写入 web_search_usage
```

预算保护（防止烧太多 credit）：

1. **月度 credit 预算**：`TAVILY_MONTHLY_CREDIT_BUDGET`（默认 800，免费档 1000 预留 200 安全余量）。通过 `SELECT SUM(credits_used) FROM web_search_usage WHERE created_at >= 月初` 查询月度消耗，超预算则跳过联网搜索。
2. **单选题 credit 预算**：`TAVILY_PER_TOPIC_CREDIT_BUDGET`（默认 3）。单个选题联网搜索消耗超限时停止。
3. **search_depth**：basic=1 credit/次，advanced=2 credits/次。
4. **WEB_SEARCH_ENABLED** 默认关闭，关闭后只用本地文章库生成资料卡，不发起联网搜索。

## 9. 路由设计

### 9.1 页面路由

当前 app.py 共 37 个路由：

```text
GET  /                                    首页 dashboard
GET  /sources                             来源库
GET  /sources/new                         新增来源页
POST /sources                             新增来源
POST /sources/fetch-all                   抓取全部启用来源
GET  /sources/{source_id}/edit            编辑来源页
POST /sources/{source_id}                 更新来源
POST /sources/{source_id}/toggle          启用/停用来源
POST /sources/{source_id}/fetch           抓取单个来源

GET  /articles                            文章池
POST /articles/bulk-ignore                批量忽略文章
GET  /articles/{article_id}               文章详情
POST /articles/{article_id}/ignore        忽略文章
POST /articles/{article_id}/edit          人工修正标题/正文
POST /articles/{article_id}/regenerate-topic  单篇文章重新生成选题
POST /articles/{article_id}/add-to-topic      手动关联文章到选题

GET  /topics                              选题库
GET  /topics/{topic_id}                   选题详情
POST /topics/generate                     生成选题
POST /topics/{topic_id}/select            选中选题
POST /topics/{topic_id}/archive           归档选题
POST /topics/{topic_id}/refresh-research-card  刷新选题资料卡
POST /topics/{topic_id}/research-card          编辑资料卡

GET  /topics/{topic_id}/scripts/compare   脚本版本对比
GET  /topics/{topic_id}/scripts           脚本编辑页
POST /topics/{topic_id}/scripts           生成脚本
POST /scripts/{script_id}                 保存脚本
GET  /scripts/{script_id}/restore         恢复历史版本
POST /scripts/{script_id}/assets          生成发布素材包
GET  /scripts/{script_id}/fact-check      事实检查

GET  /settings                            设置页
POST /settings/profile                    更新账号人设
POST /settings/model                      更新模型配置

GET  /jobs                                任务列表
POST /jobs/{job_id}/retry                 重试任务
GET  /jobs/{job_id}/status                查询任务状态
GET  /healthz                             健康检查
```

V0.3 新增路由：`refresh-research-card` / `research-card`（编辑资料卡）/ `restore`（恢复历史版本）/ `fact-check`（事实检查）/ `assets`（生成素材包）。

### 9.2 HTMX 局部刷新

适合用 HTMX 的位置：

1. 抓取按钮点击后刷新任务状态。
2. 选题卡状态切换。
3. 生成脚本后局部替换编辑区。
4. 任务列表自动刷新。

## 10. 检索设计

### 10.1 文章池检索

```sql
SELECT *
FROM articles
WHERE title LIKE CONCAT('%', %s, '%')
   OR content_text LIKE CONCAT('%', %s, '%')
ORDER BY published_at DESC
LIMIT 100;
```

当前代码已通过 `002_fulltext.sql` 建立 MySQL FULLTEXT/ngram 索引：

```sql
CREATE FULLTEXT INDEX idx_articles_fulltext ON articles(title, content_text) WITH PARSER ngram;
```

查询策略：

```sql
SELECT a.*, MATCH(a.title, a.content_text) AGAINST(%s IN BOOLEAN MODE) AS relevance
FROM articles a
WHERE MATCH(a.title, a.content_text) AGAINST(%s IN BOOLEAN MODE)
ORDER BY relevance DESC, a.fetched_at DESC
LIMIT %s OFFSET %s;
```

实现约束：

1. 查询长度 >= 2 时使用 FULLTEXT。
2. 查询长度 < 2 时回退 LIKE，避免 ngram 最小 token 限制导致查不到。
3. 查询字符串用短语形式包裹，降低 `C++`、`GPT-4` 等特殊字符破坏 BOOLEAN MODE 的风险。

### 10.2 资料卡本地检索

生成选题资料卡时，使用同一套 FULLTEXT/ngram 索引检索本地文章库，为资料卡提供来源素材。

检索策略：

```sql
SELECT a.*, MATCH(a.title, a.content_text) AGAINST(%s IN BOOLEAN MODE) AS relevance
FROM articles a
WHERE a.status = 'processed'
  AND MATCH(a.title, a.content_text) AGAINST(%s IN BOOLEAN MODE)
ORDER BY relevance DESC, a.published_at DESC
LIMIT %s;
```

检索逻辑：

1. 以选题标题、关键词、关联文章标题为 query 构造检索。
2. 只检索已处理（processed）的文章，避免抓取未完成的文章污染资料卡。
3. 按相关度 + 发布时间排序，优先使用最新且最相关的文章。
4. 检索结果写入 `topic_research_sources`（source_type='local'），关联 `article_id`。
5. 本地来源不足且 `WEB_SEARCH_ENABLED=true` 时，触发联网搜索补充（见 8.8）。

## 11. 配置设计

.env 示例：

```text
APP_ENV=development
APP_HOST=127.0.0.1
APP_PORT=8000

# MySQL
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=koubo
DB_PASSWORD=koubo
DB_NAME=koubo

# LLM
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-4o-mini

# 抓取（建议用浏览器 UA，避免被 SSR 站点返回空壳 HTML）
FETCH_USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36

# 后台任务
JOB_HEARTBEAT_TIMEOUT_SECONDS=300
JOB_POLL_INTERVAL_SECONDS=2.0

# 定时调度
SCHEDULER_ENABLED=true
SCHEDULER_FETCH_CHECK_INTERVAL_MINUTES=30
SCHEDULER_TOPIC_ENABLED=false
SCHEDULER_TOPIC_CRON=30 9 * * *

# 联网搜索（V0.3，默认关闭）
WEB_SEARCH_ENABLED=false
WEB_SEARCH_PROVIDER=tavily
TAVILY_API_KEY=
TAVILY_SEARCH_DEPTH=basic
TAVILY_MAX_RESULTS=10
TAVILY_EXTRACT_MAX_URLS=5
TAVILY_MONTHLY_CREDIT_BUDGET=800
TAVILY_PER_TOPIC_CREDIT_BUDGET=3

LOG_LEVEL=INFO
```

说明：

1. DEFAULT_LLM_PROVIDER 和 DEFAULT_LLM_MODEL 只用于首次初始化 llm_settings。应用运行后以页面保存的模型配置为准。
2. Docker 运行时 compose 默认覆盖 DB_HOST=host.docker.internal，让 app 容器访问宿主机 MySQL。
3. SCHEDULER_ENABLED 控制自动抓取调度；SCHEDULER_TOPIC_ENABLED 默认关闭，避免自动消耗 LLM。
4. OPENAI_BASE_URL 当前作为预留配置存在；若要接入第三方 OpenAI 兼容网关，需要在 `services/llm.py` 中把 base_url 注入 OpenAI client。
5. FETCH_USER_AGENT 建议使用浏览器 UA，避免被 SSR 站点（如 InfoQ）当作爬虫返回空壳 HTML。
6. WEB_SEARCH_* / TAVILY_* 为 V0.3 联网搜索配置。WEB_SEARCH_ENABLED 默认关闭，关闭后只用本地文章库生成资料卡。TAVILY_API_KEY 需在 https://tavily.com 注册获取（免费档 1000 credits/月）。TAVILY_MONTHLY_CREDIT_BUDGET 默认 800（预留 200 安全余量），TAVILY_PER_TOPIC_CREDIT_BUDGET 默认 3（防止单选题烧太多额度）。

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

### 方式一：Docker（推荐）

`docker-compose.yml` 同时编排 app + mysql 两个容器，MySQL 数据通过 volume 持久化到宿主机。

```bash
# 复制环境变量模板并填入 OPENAI_API_KEY（可选）
cp .env.example .env
docker compose up -d --build
```

容器监听 `0.0.0.0:8000`。代码变更部署必须用 `docker compose up -d --build app`（restart 不会用新代码）：

```bash
# 代码变更后重新部署（重新构建镜像 + 启动）
docker compose up -d --build app

# 仅重启（不会用新代码，仅用于配置变更场景）
docker compose restart app
```

访问：

```text
http://127.0.0.1:8000
```

### 方式二：本地直接运行

需先准备 MySQL 8.0 实例并建库授权：

```sql
CREATE DATABASE koubo CHARACTER SET utf8mb4;
CREATE USER 'koubo'@'%' IDENTIFIED BY 'koubo';
GRANT ALL ON koubo.* TO 'koubo'@'%';
```

然后：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

应用启动时会自动执行 migration 建表，并写入默认 creator_profile 与 llm_settings。

## 15. 当前实现里程碑

### V0.1 核心闭环

1. FastAPI + Jinja2 单体应用。
2. MySQL 8.0 schema、migration 与 schema_migrations 幂等执行。
3. 来源库 CRUD、启用/停用、单源抓取、抓取全部启用来源。
4. RSS/普通网页抓取、正文提取、URL 规范化、content_hash/source_item/canonical_url 去重。
5. 文章池列表、详情、搜索、来源筛选、分页、无正文筛选、单篇/批量忽略。
6. 内容卡生成、文章摘要保存、topic/topic_facts/topic_articles 入库。
7. 选题库筛选、选中/归档、脚本生成。
8. 脚本版本保存、编辑、设置页人设和模型配置。
9. MySQL jobs 队列、worker、重试、启动恢复和任务状态页。

### V0.2 已补充能力

1. MySQL FULLTEXT/ngram 文章搜索。
2. 单篇文章人工修正正文后重新生成选题。
3. 近 7 天标题相似度去重与重复选题合并。
4. 脚本版本对比。
5. 发布素材包生成与 script_assets 存储。
6. APScheduler 到期来源抓取调度；选题自动调度可配置但默认关闭。
7. Docker app 容器化运行，连接宿主机或外部 MySQL。
8. 种子来源脚本 `scripts/seed_sources.py`。

### V0.3 已补充能力

1. **选题资料卡**（research_card_generator.py）：本地文章库 FULLTEXT 检索 + LLM 生成结构化资料卡 JSON，写入 topic_research_cards + topic_research_sources，scripts.research_card_id 关联。
2. **联网搜索**（web_search.py + Tavily provider）：本地资料不足时按配置联网补充，含单选题/月度 credit 预算保护（web_search_usage 追踪消耗）。
3. **事实校验**（fact_checker.py）：抽取脚本事实性声明，检查 topic_facts/关联文章来源，标记高风险表述，提供 `/scripts/{id}/fact-check` 页面。
4. **来源可信度评分**（credibility_scorer.py）+ **来源分类**（source_classifier.py）。
5. **三模板脚本生成**（script_generator.py）：热点解读=新闻评论式 / 工具教程=实操教学式 / 观点拆解=辩论式，字数按 duration 动态计算（duration*5~7），temperature=0.9，生成后字数校验告警。
6. **并发 worker**：升级为 ThreadPoolExecutor(max_workers=3)，慢任务不阻塞快任务。
7. **前后端双重防重复锁**：前端按钮防抖禁用 + 后端 409 Conflict 检查（list_active_jobs_by_type 去重）。
8. **脚本版本管理**：按 (platform, format, duration) 分组展示 + 历史版本折叠 + restore 接口恢复历史版本。
9. **选题去重**：Jaccard 2-gram 标题相似度（阈值 0.6，7 天窗口），重复内容合并到已有选题。
10. **选题评分**：7 维度规则评分（新鲜度 20 + 来源权威度 20 + 实操价值 20 + 可理解度 15 + 反差争议 10 + 平台适配 10 + 人设匹配 5），新鲜度按 published_at 计算（7 天内无惩罚，之后每 7 天扣 2 分上限 10 分，缺日期扣 6 分）。
11. **文章池排序**：published_at DESC + FIELD(s.level, 'S','A','B','C')。
12. **摘要服务**（summarizer.py）：文章级摘要 + key_points。
13. **反爬策略**：per-host throttling + exponential backoff + circuit breaker + 浏览器 UA + _REFETCH_SKIP_HOSTS。
14. **抓取来源类型扩展**：新增 webpage_list / spa_list / github_topics / bilibili_search，共支持 7 种类型。
15. **render_prompt helper**：替代 str.format，避免 JSON 花括号冲突；prompt 支持热更新（文件 mtime 检测）。
16. **Docker app + mysql 双容器编排**：MySQL 数据通过 volume 持久化到宿主机。
17. **prompt 热更新**：5 个 prompt 文件支持文件 mtime 检测，无需重启。

### 仍未实现 / 后续 TODO

1. 视频表现反馈录入。
2. 选题评分自动校准。
3. 多账号人设配置。
4. 自动发布或平台 API 集成。

## 16. 后续可升级方向

后续再考虑：

1. MySQL 单机 -> MySQL 主从 / 云数据库 RDS。
2. MySQL FULLTEXT -> 向量检索 / 语义聚类。
3. 本地应用 -> VPS 部署。
4. 发布素材包 -> 平台发布清单 / 半自动发布流程。
5. 单账号人设 -> 多账号人设配置。
6. 手动反馈录入 -> 自动化内容表现复盘。
