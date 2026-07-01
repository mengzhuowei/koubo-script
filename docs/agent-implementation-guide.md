# Agent Implementation Guide

版本：V0.1

用途：给开发 Agent 读取的实施指南。目标是收窄开发自由度，让 Agent 能按固定顺序实现 MVP。

## 1. 必读顺序

开发前必须按顺序读取：

1. `docs/mvp-spec.md`
2. `docs/technical-architecture.md`
3. `docs/product-design.md`

本文件优先级高于其他文档中的宽泛设想。若文档冲突，以 MVP 范围和本实施指南为准。

## 2. 开发目标

实现一个本地运行的 Python 单体 Web 应用，跑通以下闭环：

```text
来源库 -> 抓取文章 -> 清洗去重 -> 文章摘要 -> 内容卡 -> 选题评分 -> 口播脚本 -> 保存版本
```

启动方式：

```bash
python app.py
```

访问地址：

```text
http://127.0.0.1:8000
```

## 3. 技术选择锁定

必须使用：

1. FastAPI
2. Jinja2
3. MySQL 8.0（通过 pymysql + DictCursor 访问）
4. Python 标准线程或简单 worker loop
5. 普通 CSS
6. requests/feedparser/trafilatura/BeautifulSoup 组合做抓取和正文提取

允许使用：

1. HTMX，用于局部刷新。
2. APScheduler，用于后续定时创建任务。
3. python-dotenv 或 pydantic-settings，用于配置。
4. Docker + docker-compose，用于一键启动 app + mysql。

不要使用：

1. React、Vue、Next.js。
2. PostgreSQL、MongoDB。
3. Redis、Celery、RQ。
4. Elasticsearch、Meilisearch、向量数据库。
5. 登录系统和复杂权限。
6. 自动发布到抖音/小红书。

## 4. 推荐项目结构

按以下结构创建文件。不要先引入复杂分层之外的新目录。

```text
.
├── app.py
├── config.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── migrations/
│   └── 001_init.sql          # MySQL 8.0 方言
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
│   ├── script_editor.html
│   ├── settings.html
│   └── jobs.html
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
│   ├── topic_generator.py
│   ├── scorer.py
│   └── script_generator.py
├── workers/
│   └── job_runner.py
└── prompts/
    ├── content_card.md
    ├── topic_score.md
    └── script_koubo.md
```

## 5. 开发顺序

严格按以下顺序实现。每一步完成后运行应用做一次手动检查。

### Step 1: 项目骨架

创建：

1. `requirements.txt`
2. `config.py`
3. `app.py`
4. `templates/base.html`
5. `templates/dashboard.html`
6. `templates/settings.html`
7. `static/app.css`
8. `static/app.js`

完成标准：

1. `python app.py` 能启动。
2. 首页能打开。
3. 页面有基础导航：首页、来源库、文章池、选题库、任务、设置。

### Step 2: 数据库初始化

创建：

1. `migrations/001_init.sql`
2. `repositories/db.py`

必须包含这些表：

1. `sources`
2. `articles`
3. `topics`
4. `topic_articles`
5. `topic_facts`
6. `scripts`
7. `creator_profile`
8. `llm_settings`
9. `jobs`

完成标准：

1. 应用启动时自动执行 migration 建表（通过 schema_migrations 表保证幂等，重复执行不报错）。
2. migration 可重复执行，不破坏已有数据。
3. 默认插入一条 creator_profile：AI效率教练。
4. 默认插入一条 llm_settings，provider/model 来自 .env 初始值。

### Step 3: 来源库

创建：

1. `repositories/sources_repo.py`
2. `templates/sources.html`
3. `templates/source_form.html`

实现路由：

```text
GET  /sources
GET  /sources/new
POST /sources
GET  /sources/{id}/edit
POST /sources/{id}
POST /sources/{id}/toggle
POST /sources/{id}/fetch
```

MVP 来源类型只需要支持：

1. `rss`
2. `webpage`
3. `manual`

完成标准：

1. 可以新增来源。
2. 可以编辑来源。
3. 可以启用/停用来源。
4. 来源列表显示 level、type、enabled、last_fetched_at、last_error。

### Step 4: 抓取和文章入库

创建：

1. `services/crawler.py`
2. `services/cleaner.py`
3. `repositories/articles_repo.py`
4. `templates/articles.html`
5. `templates/article_detail.html`

实现：

1. RSS 抓取。
2. 普通网页抓取。
3. 正文提取。
4. URL 规范化。
5. content_hash 去重。
6. source_item_id 去重。

实现路由：

```text
GET  /articles
GET  /articles/{id}
POST /articles/{id}/ignore
```

完成标准：

1. 点击来源抓取后能新增 articles。
2. 重复抓取不会重复插入同一文章。
3. 文章池能搜索标题和正文。
4. 文章详情能查看标题、来源、URL、正文。

### Step 5: Jobs 队列

创建：

1. `repositories/jobs_repo.py`
2. `workers/job_runner.py`
3. `templates/jobs.html`

实现 job type：

```text
fetch_source
fetch_all_sources
process_article
generate_topic
generate_script
```

实现路由：

```text
GET  /jobs
POST /jobs/{id}/retry
```

完成标准：

1. 任务有 pending/running/done/failed 状态。
2. running 任务写入 locked_by 和 heartbeat_at。
3. 应用启动时恢复超时 running 任务。
4. 失败任务可手动重试。

### Step 6: LLM 封装

创建：

1. `services/llm.py`
2. `prompts/content_card.md`
3. `prompts/topic_score.md`
4. `prompts/script_koubo.md`
5. `repositories/settings_repo.py`

要求：

1. 所有 LLM 调用只通过 `services/llm.py`。
2. LLM 调用必须读取 `llm_settings` 的 provider、model、temperature、max_tokens。
3. API Key 从 `api_key_env_var` 指向的环境变量读取，不允许入库或页面显示明文。
4. 若没有配置 API Key，返回清晰错误，不让应用崩溃。
5. JSON 输出必须有解析和错误提示。

完成标准：

1. 可以从代码调用 LLM 生成内容卡 JSON。
2. 可以生成口播脚本文本。
3. LLM 失败时 job 标记 failed，并保存错误。
4. 修改 llm_settings 后，新任务使用新模型配置。

### Step 7: 设置页

创建：

1. `templates/settings.html`
2. 完善 `repositories/settings_repo.py` 的读写方法

实现路由：

```text
GET  /settings
POST /settings/profile
POST /settings/model
```

完成标准：

1. 可以编辑人设名称、定位、目标受众、语气、内容边界、默认 CTA。
2. 可以编辑 provider、model、temperature、max_tokens。
3. 页面显示 API Key 是否已配置，但不显示密钥内容。
4. 保存后写入 creator_profile 和 llm_settings。

### Step 8: 内容卡和选题库

创建：

1. `services/topic_generator.py`
2. `services/scorer.py`
3. `repositories/topics_repo.py`
4. `templates/topics.html`
5. `templates/topic_detail.html`

实现路由：

```text
GET  /topics
GET  /topics/{id}
POST /topics/generate
POST /topics/{id}/select
POST /topics/{id}/archive
POST /articles/{id}/add-to-topic
```

完成标准：

1. 可以从文章生成 topic。
2. topic 保存 title、one_line_takeaway、summary、score、actionable_value、risk_notes。
3. 至少保存一条 topic_fact。
4. 选题库按 score 倒序展示。
5. 选题详情展示关联文章和来源链接。
6. 内容卡生成使用设置页中的人设和模型配置。

### Step 9: 脚本生成和保存

创建：

1. `services/script_generator.py`
2. `repositories/scripts_repo.py`
3. `templates/script_editor.html`

实现路由：

```text
GET  /topics/{id}/scripts
POST /topics/{id}/scripts
POST /scripts/{id}
```

完成标准：

1. 可以选择 platform：douyin / xiaohongshu。
2. 可以选择 format：热点解读 / 工具教程 / 观点拆解。
3. 可以选择 duration：60 / 90 / 180。
4. 可以生成脚本。
5. 可以编辑脚本并保存。
6. 同一 topic/platform/format/duration 再生成时 version 自动递增。
7. 脚本生成使用设置页中的人设和模型配置。

## 6. 数据库实现要求

### migration

`migrations/001_init.sql` 必须是最终可执行 MySQL 8.0 SQL，不要只写伪代码。通过 `schema_migrations` 表记录已应用版本，重复执行时对 1050/1060/1061/1091（表/列/索引已存在或不存在）错误幂等跳过。

### 连接

`repositories/db.py` 用 pymysql + DictCursor + autocommit=True，并提供 `_Conn` 包装器让 repository 层沿用 `conn.execute(sql, args).fetchone()` 写法。会话时区设为 `+00:00`，让 `CURRENT_TIMESTAMP` 返回 UTC，全应用时间口径统一。

### timestamps

所有时间字段统一用 MySQL `CURRENT_TIMESTAMP`（会话时区已设为 UTC）。不要混用多种格式。

### JSON 字段

以下字段可用 TEXT 保存 JSON：

1. `sources.config_json`
2. `topics.audience`
3. `scripts.hashtags`
4. `jobs.payload_json`

读写时必须在 repository 或 service 层完成 JSON encode/decode。

### SQL 占位符

MySQL 使用 `%s` 占位符。字符串拼接用 `CONCAT()`，日期运算用 `DATE_ADD()` / `DATE()`，时间戳差用 `UNIX_TIMESTAMP()`。

## 7. UI 要求

MVP UI 要求简单、密集、可操作。

必须有：

1. 顶部导航。
2. 表格列表。
3. 状态标签。
4. 表单错误提示。
5. 空状态提示。
6. 明确的主操作按钮。

不要做：

1. 营销落地页。
2. 大 hero 区。
3. 花哨动效。
4. 复杂主题切换。
5. 大量装饰图片。

## 8. Prompt 要求

### 内容卡 Prompt

必须要求模型输出 JSON：

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

### 脚本 Prompt

必须包含从 creator_profile 读取的人设。默认人设是：

```text
你是一个 AI效率教练。
你的任务不是炫耀前沿技术，而是把 AI Agent 技术拆成普通人能执行的工作流。
```

注意：以上只是默认值，不允许在 prompt 文件或 service 代码里写死。生成 prompt 时必须从数据库读取当前 creator_profile。

脚本必须包含：

1. 观众痛点。
2. 常见错误。
3. 正确工作流。
4. 4-6 个步骤。
5. 一句可复制提示词。
6. 一个 “X 不是 Y” 的区分。
7. 风险提醒。
8. 人设 CTA。

## 9. 第一批种子来源

MVP 可先手动添加这些来源，优先 RSS 或普通网页：

1. OpenAI Blog
2. OpenAI Developers / Agents docs
3. Anthropic News
4. Anthropic Engineering
5. Model Context Protocol Docs
6. LangChain Blog
7. LlamaIndex Blog
8. CrewAI Blog
9. Hugging Face Blog
10. Google ADK Docs

如果某个来源难以自动抓取，允许先作为 manual 来源录入链接。

## 10. 验收 Checklist

交付前必须确认：

1. `python app.py` 能启动。
2. 首页可访问。
3. 来源库可新增、编辑、停用。
4. 至少能抓取一个 RSS 来源。
5. 至少能抓取一个普通网页来源。
6. 文章重复抓取不会重复入库。
7. 文章池可搜索。
8. 能生成内容卡。
9. 能生成口播脚本。
10. 脚本可以保存新版本。
11. jobs 页面能看到任务状态。
12. 设置页可以修改人设。
13. 设置页可以修改模型配置。
14. 修改人设后，新生成脚本使用新人设。
15. 修改模型后，新 LLM 调用使用新模型配置。
16. 没有 API Key 时应用不崩溃。
17. 重启应用后数据仍在。

## 11. 开发边界

如果实现过程中遇到超出 MVP 的想法，先记录为 TODO，不要直接实现。

允许 TODO：

1. MySQL FULLTEXT 全文搜索。
2. GitHub/arXiv/HN 专用适配器。
3. 定时任务。
4. 发布素材包。
5. 事实校验。
6. 视频表现反馈。

不要为了 TODO 改变现有架构。
