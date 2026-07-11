# AI Agent Efficiency Coach MVP Spec

版本：V0.1

> **实现状态**：本文档为 V0.1 MVP 规格，MVP 闭环已于 V0.1 阶段完成。后续能力扩展见 docs/technical-architecture.md 和 docs/product-design.md。

目标：用最小可用版本跑通“抓取内容 -> 生成内容卡 -> 生成口播脚本 -> 保存版本”的核心闭环。

## 1. MVP 范围

### 必做

1. 本地 FastAPI + Jinja2 应用。
2. MySQL 8.0 初始化和基础数据表。
3. 来源库管理。
4. RSS 和普通网页抓取。
5. 文章清洗、去重、入库。
6. 文章摘要和关键点保存。
7. 内容卡生成。
8. 选题评分。
9. 脚本生成。
10. 脚本保存和版本递增。
11. 简单 jobs 队列和任务状态页。
12. 人设设置页。
13. 模型设置页。

### 暂不做

1. 自动发布到抖音/小红书。
2. 完整发布素材包（V0.2 已实现）。
3. 多用户登录和权限。
4. 向量数据库。
5. 多 worker 并发（V0.3 已实现，ThreadPoolExecutor max_workers=3）。
6. 平台竞品自动抓取。
7. 复杂数据看板。

## 2. 第一批页面

### 首页

显示：

1. 今日抓取文章数。
2. 今日新增选题数。
3. 高分选题 Top 10。
4. 最近脚本。
5. 最近任务状态。

操作：

1. 抓取全部来源。
2. 生成选题。
3. 进入来源库。
4. 进入选题库。

### 来源库

功能：

1. 新增来源。
2. 编辑来源。
3. 启用/停用来源。
4. 手动抓取单个来源。
5. 查看 last_fetched_at 和 last_error。

MVP 支持来源类型：

1. rss
2. webpage
3. manual

github、arxiv、HN 作为 V0.2 或之后的专用适配器。

### 文章池

功能：

1. 文章列表。
2. 按关键词搜索。
3. 按来源筛选。
4. 查看文章详情。
5. 标记 ignored。
6. 手动加入已有选题。

### 选题库

功能：

1. 按分数排序。
2. 按栏目筛选。
3. 查看内容卡。
4. 标记 selected / archived。
5. 进入脚本生成页。

### 脚本编辑页

功能：

1. 选择平台：douyin / xiaohongshu。
2. 选择模板：热点解读 / 工具教程 / 观点拆解。
3. 选择时长：60 / 90 / 180。
4. 生成脚本。
5. 编辑并保存脚本。
6. 新版本自动递增。

### 设置页

功能：

1. 修改账号人设：名称、定位、目标受众、语气、内容边界、默认 CTA。
2. 修改模型配置：provider、model、temperature、max_tokens。
3. 显示 API Key 是否已通过环境变量配置。
4. 保存后立即影响后续内容卡和脚本生成。

## 3. 核心数据闭环

```text
sources
  -> articles
  -> article summary/key_points
  -> topics
  -> topic_facts
  -> scripts
```

设置数据：

```text
creator_profile
llm_settings
```

要求：人设和模型不能写死在 service 或 prompt 代码里，必须从数据库读取。

MVP 要求每个 topic 至少有：

1. title
2. one_line_takeaway
3. summary
4. score
5. actionable_value
6. risk_notes
7. 至少 1 条 topic_fact

MVP 要求每个 script 至少有：

1. title
2. hook
3. body
4. cta
5. platform
6. format
7. duration
8. version

## 4. Jobs 队列

### 必做 job type

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

### 任务状态

```text
pending
running
done
failed
```

### 可靠性要求

1. running 任务必须写 heartbeat_at。
2. 启动时恢复超时 running 任务。
3. 失败任务记录 error。
4. 失败次数未超过 max_attempts 时允许重试。

## 5. LLM 输出要求

### 内容卡

必须输出 JSON，并能入库到 topics 和 topic_facts。

### 脚本

必须符合设置页配置的人设，默认人设为“AI效率教练”：

1. 开头 3 秒给痛点或结果。
2. 说明一个常见错误。
3. 给出正确工作流。
4. 包含 4-6 个步骤。
5. 包含一句可复制提示词。
6. 包含一个 “X 不是 Y” 的区分。
7. 包含风险提醒。
8. 结尾使用人设 CTA。

## 6. 验收标准

MVP 完成时，应该能做到：

1. 启动 `python app.py` 后打开本地页面。
2. 添加 3 个 RSS 或网页来源。
3. 点击抓取后能看到文章入库。
4. 对文章生成摘要。
5. 生成至少 3 个内容卡。
6. 从内容卡生成 1 条 90 秒抖音口播脚本。
7. 修改并保存脚本版本。
8. 在设置页修改人设后，新生成脚本能使用新人设。
9. 在设置页修改模型名称后，LLM 调用读取新模型配置。
10. 重启应用后数据不丢失。

## 7. 推荐开发顺序

> MVP 已按此顺序完成。

1. 数据库初始化和 migration。
2. FastAPI/Jinja2 页面骨架。
3. 来源库 CRUD。
4. RSS 抓取和文章入库。
5. 文章池页面。
6. jobs 队列。
7. LLM 封装。
8. 设置页。
9. 内容卡生成。
10. 选题库页面。
11. 脚本生成和保存。
