# 口播雷达 · Koubo Script

把分散的 AI 资讯，整理成有来源、有观点、能开口讲的短视频脚本。

口播雷达是一个可自部署的中文口播内容创作工作台，面向 AI 工具、Agent 和效率工作流方向的内容创作者。它把信息采集、选题筛选、资料整理、脚本写作和发布文案放在同一个工作台里，帮助你减少反复找资料、切换工具和整理提示词的时间。

你可以从官方博客、技术社区、论文和项目动态中寻找选题，查看评分与来源依据，再根据自己的账号人设，为抖音、小红书生成不同结构和时长的口播脚本。

## 为什么做这个项目

做技术类短视频，写稿之前往往还有很多工作：信息散落在不同网站，同一件事有多个版本，技术资料需要转成观众听得懂的表达，热点也未必适合自己的账号。

口播雷达把这些准备工作串起来，让创作者能围绕同一个选题持续整理证据、打磨表达、比较版本，最后形成可供录制和发布的文字素材。

```text
信息源 → 文章池 → 选题与评分 → 选题资料卡 → 口播脚本 → 事实校验 → 发布素材包
                                      ↑
                              可选联网搜索补充资料
```

## 核心功能

| 功能 | 可以做什么 |
| --- | --- |
| 多来源采集 | 支持 RSS、普通网页、列表页、SPA 列表、GitHub Topics、B 站搜索和人工维护来源；支持来源分级、启停和定时抓取 |
| 文章池 | 清洗正文、去重、中文全文搜索、来源筛选、分页、批量忽略，也可以人工修正正文 |
| 选题生成与评分 | 从文章生成内容卡、聚合相似选题；结合模型评估和规则计算，展示内容价值、证据强度、来源权威度、新鲜度等评分依据 |
| 选题资料卡 | 汇总关键事实、参考来源和风险提示；优先检索本地文章库，可选通过 Tavily 联网补充资料 |
| 口播脚本生成 | 支持抖音、小红书，以及「热点解读」「工具教程」「观点拆解」三种叙事结构，可指定目标时长 |
| 人设配置 | 自定义账号名称、定位、受众、语气、内容边界和行动引导，让内容保持统一风格 |
| 版本管理 | 编辑、保存、对比和恢复脚本历史版本，按平台、结构和时长分组查看 |
| 事实校验 | 抽取脚本中的事实性声明，对照已有资料与来源，标记需要人工复核的表述 |
| 发布素材包 | 基于脚本生成标题、封面文案、简介、标签、评论引导和置顶评论 |
| 项目助手 | 用自然语言查询文章、选题和任务，提交抓取、选题与脚本生成请求，查看工具执行进度和结果入口 |
| 附件问答 | 项目助手可读取 TXT、Markdown、JSON、CSV、TSV、PDF、DOCX 和 XLSX 附件；每个附件最多 5 MB，每轮最多 6 个 |
| 后台任务 | 支持并发执行、状态跟踪、失败重试和启动恢复；联网搜索提供单选题与月度预算控制 |

例如，你可以在项目助手中输入：

- 「帮我看看今天有哪些值得讲的选题。」
- 「查询文章池里和 MCP 有关的内容。」
- 「给选题 #12 生成一篇 90 秒的抖音工具教程脚本。」
- 「查看失败的后台任务。」

## 适合谁

- 持续制作 AI 工具、Agent、自动化和效率教程的短视频创作者。
- 需要从技术资讯中寻找内容角度的知识博主、独立开发者和小团队。
- 希望自定义信息源、人设和提示词，搭建自己内容工作流的开发者。

项目默认人设为「AI 效率教练」，可以在设置页修改。当前内置的信息源、栏目和提示词主要围绕 AI / Agent 内容设计。

## 技术栈

- **应用**：Python 3.11、FastAPI、Jinja2，服务端渲染页面。
- **数据**：MySQL 8.0+、PyMySQL，使用 FULLTEXT / ngram 支持中文全文检索。
- **采集**：feedparser、Requests、Trafilatura、BeautifulSoup、Playwright。
- **模型**：OpenAI Python SDK，支持配置 OpenAI 兼容接口。
- **项目助手**：Node.js、Pi Agent，通过受约束的业务工具操作工作台。
- **后台处理**：MySQL 任务队列、线程池、APScheduler。
- **部署**：Docker / Docker Compose，或本地 Python 环境。

## 快速开始

### 1. 准备数据库

准备一个可访问的 MySQL 8.0+ 实例，并创建数据库和应用用户。下方密码为占位值，请替换后执行：

```sql
CREATE DATABASE koubo CHARACTER SET utf8mb4;
CREATE USER 'koubo'@'%' IDENTIFIED BY 'replace-with-your-password';
GRANT ALL PRIVILEGES ON koubo.* TO 'koubo'@'%';
```

应用会在启动时自动执行 `migrations/` 中的建表和升级脚本，并初始化默认人设与模型设置。数据库和用户需要提前创建。

### 2. 配置环境变量

在项目根目录复制 `.env.example` 为 `.env`：

```powershell
Copy-Item .env.example .env
```

macOS / Linux 使用 `cp .env.example .env`。编辑以下主要配置：

```dotenv
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=koubo
DB_PASSWORD=replace-with-your-password
DB_NAME=koubo

OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_LLM_MODEL=gpt-4o-mini
```

`OPENAI_BASE_URL` 可替换为所用服务的 OpenAI 兼容接口地址，模型名称也应与该服务一致。项目助手需要模型支持工具调用。

未配置 API Key 时可以使用来源和文章管理等功能；内容生成与项目助手需要有效的模型配置。模型调用和可选联网搜索的费用由相应服务收取。

### 3. 启动应用

#### 方式一：本地运行

准备 Python 3.11+。如需使用项目助手，还需要 Node.js 22.19.0+。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
npm ci --prefix pi-agent --ignore-scripts
python app.py
```

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm ci --prefix pi-agent --ignore-scripts
python app.py
```

使用 SPA 类型来源时，额外安装 Chromium；Linux 环境还需要安装浏览器的系统依赖：

```bash
python -m playwright install chromium
# Linux 环境按需执行：python -m playwright install-deps chromium
```

#### 方式二：Docker Compose

Compose 示例只启动应用容器，MySQL 需自行部署。镜像已包含 Node.js 和项目助手依赖。

```powershell
Copy-Item docker-compose.yml.example docker-compose.yml
```

macOS / Linux 使用 `cp docker-compose.yml.example docker-compose.yml`。

如果 MySQL 位于宿主机，将 `.env` 中的 `DB_HOST` 改为 `host.docker.internal`；如果位于其他机器或容器，填写应用容器可访问的地址。然后运行：

```bash
docker compose up -d --build
```

Windows / macOS 若无法挂载 `/etc/localtime`，可移除 Compose 中对应的卷挂载，保留 `TZ` 环境变量。当前 Dockerfile 中 Chromium 安装步骤处于注释状态，使用 SPA 来源前需要启用相应步骤并重新构建镜像。

数据库内容保存在外部 MySQL 中，请在数据库侧配置持久化与备份。

启动后访问 [http://127.0.0.1:8000](http://127.0.0.1:8000)。应用当前没有内置登录与权限管理，适合本机或受控网络使用。

### 4. 开始创作

1. 打开「设置」，确认模型名称，并填写自己的账号人设。
2. 在「来源库」添加信息源，或使用下方脚本导入预置来源。
3. 抓取内容，在「文章池」筛选资料并生成选题。
4. 查看选题评分和资料卡，选择平台、脚本结构与目标时长。
5. 生成并编辑脚本，按需执行事实校验、比较版本和生成发布素材包。

本地运行时，可在首次启动完成建表后，另开一个已激活虚拟环境的终端，从项目根目录导入种子来源：

```bash
python -m scripts.seed_sources
```

种子脚本会按名称或 URL 更新已有来源，包括启用状态和抓取配置；部分需人工跟踪的来源默认停用。

## 可选配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `SCHEDULER_ENABLED` | `true` | 定时检查并抓取到期来源 |
| `SCHEDULER_FETCH_CHECK_INTERVAL_MINUTES` | `30` | 来源检查间隔，单位为分钟 |
| `SCHEDULER_TOPIC_ENABLED` | `false` | 是否自动生成选题，开启后会调用模型 |
| `SCHEDULER_TOPIC_CRON` | `30 9 * * *` | 自动生成选题的调度表达式 |
| `WEB_SEARCH_ENABLED` | `false` | 是否允许联网补充资料 |
| `TAVILY_API_KEY` | 空 | 联网搜索密钥 |
| `TAVILY_MONTHLY_CREDIT_BUDGET` | `800` | 应用侧月度搜索预算 |
| `TAVILY_PER_TOPIC_CREDIT_BUDGET` | `3` | 应用侧单选题搜索预算 |

完整配置见 [.env.example](.env.example)。`DEFAULT_LLM_PROVIDER` 和 `DEFAULT_LLM_MODEL` 用于首次初始化，之后以设置页保存的模型配置为准。修改密钥或接口地址后需要重启应用；Docker 部署可执行 `docker compose up -d --force-recreate app` 以重新注入环境变量。

## 项目结构

```text
app.py          Web 入口与路由
config.py       环境配置
services/       采集、选题、评分、资料卡、脚本与助手服务
repositories/   数据访问
workers/        后台任务执行与定时调度
pi-agent/       项目助手的 Node.js 运行时
prompts/        内容卡、评分、脚本和素材包提示词
templates/      页面模板
static/         前端样式与交互
migrations/     数据库迁移
scripts/        种子来源等辅助脚本
tests/          自动化测试
docs/           产品设计与技术文档
```

## 开发与贡献

欢迎通过 Issue 反馈使用问题、提出功能建议，或通过 Pull Request 改进采集适配、提示词、脚本质量与交互体验。提交问题时请附上复现步骤和脱敏日志。

安装项目依赖后，可从根目录运行现有测试：

```bash
python -m unittest discover -s tests
```

项目助手相关测试需要 Node.js 和本地 Pi 依赖，未安装时会跳过。

## 当前边界

当前版本覆盖从选题到文字素材的创作流程，暂未提供视频制作、自动发布、多账号人设管理和内容表现复盘。事实校验用于提示风险，发布前仍需人工核对关键事实、来源和表达。
