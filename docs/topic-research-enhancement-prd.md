# 选题研究增强 PRD

版本：V0.1

> **实现状态**：本 PRD 的 V0.2.1（本地资料卡）和 V0.3（联网搜索）阶段已实现。V0.4（可信度增强）部分实现（事实校验 fact_checker.py 已落地）。详细技术实现见 docs/technical-architecture.md 第 8 节。

建议排期：V0.2.1 到 V0.4

定位：在生成口播脚本之前，先围绕选题自动整理一份结构化“选题资料卡”，再把资料卡作为脚本生成的核心上下文，让脚本更及时、更具体、更可信、更符合“AI效率教练”的内容定位。

## 1. 背景

当前系统已经可以从固定来源抓取 AI Agent 相关内容，生成选题、内容卡、口播脚本和发布素材包。

但脚本生成阶段主要依赖已有选题内容和关联文章，容易出现三个问题：

1. 选题相关资料不够完整，只能生成比较泛的脚本。
2. 对最新模型、工具、框架、产品发布的覆盖不够及时。
3. 脚本里缺少可引用的具体事实、案例、对比和使用场景。

因此需要在“选题 -> 脚本”之间增加一层“选题研究增强”，把零散资料整理成可控、可审查、可复用的中间产物。

## 2. 目标

### 2.1 产品目标

1. 生成脚本前，自动补全选题相关资料。
2. 优先使用本地文章库，减少不必要的联网搜索和成本。
3. 当本地资料不足、过旧或选题明显依赖最新信息时，再联网搜索补充。
4. 把资料整理成固定结构的“选题资料卡”。
5. 脚本生成只读取资料卡、选题、人设和脚本参数，不直接读取大量原始网页。
6. 让最终脚本包含更强的事实依据、案例解释、效率场景和风险提醒。

### 2.2 内容目标

输出内容应更像“AI效率教练”，而不是普通科技资讯播报：

1. 不只讲“发生了什么”，还要讲“这对普通人/内容创作者/小团队怎么提效”。
2. 不只复述技术名词，还要转成可执行工作流。
3. 不盲目追热点，要说明适用边界和风险。
4. 保留来源，方便用户回看和二次判断。

## 3. 非目标

本需求不包含：

1. 自动发布到抖音或小红书。
2. 大规模通用搜索引擎系统。
3. 向量数据库。
4. 复杂事实校验工作流。
5. 多用户协作。
6. 评论区、点赞、播放量等视频表现自动回流。
7. 对网页内容做全文永久镜像。

事实校验、向量检索和视频反馈可以作为后续独立版本建设。

## 4. 用户故事

### Story 1：生成脚本前自动准备资料卡

作为内容创作者，我希望系统在生成脚本前自动准备一份选题资料卡，这样我不需要额外点击，也能确认这个选题是否有足够事实支撑。

验收标准：

1. 用户进入脚本生成页时，系统自动检查当前选题是否已有可用资料卡。
2. 如果没有资料卡，系统自动基于本地文章库生成资料卡。
3. 如果资料卡已过期或关联资料发生明显变化，系统提示需要刷新，但不阻断脚本生成。
4. 点击“生成脚本”时，如果仍没有可用资料卡，系统先自动生成资料卡，再生成脚本。
5. 资料卡保存后，脚本生成默认使用这份资料卡。
6. 页面保留“刷新资料卡”按钮，供用户手动重建资料卡。

### Story 2：本地资料不足时联网补充

作为内容创作者，我希望系统在资料不足时能按配置自动搜索网上新资料，这样脚本不会漏掉最近的重要更新。

验收标准：

1. 本地资料不足时，系统提示“需要联网补充”。
2. 如果联网搜索已开启、API Key 已配置且未超过预算，系统可以自动执行联网补充。
3. 如果联网搜索未开启、API Key 未配置或预算不足，系统不自动联网，只生成本地资料卡并提示原因。
4. 联网搜索结果必须保存来源 URL、标题、发布时间和摘要。
5. 联网搜索默认有数量上限，避免过度抓取。

### Story 3：资料卡可编辑

作为内容创作者，我希望可以编辑资料卡，这样我可以删掉不适合口播的点，补充自己的判断。

验收标准：

1. 资料卡字段可以在页面中查看。
2. 用户可以手动编辑资料卡正文 JSON 或结构化字段。
3. 保存后再次生成脚本会使用最新资料卡。
4. 保留资料卡版本或更新时间。

### Story 4：脚本展示资料依据

作为内容创作者，我希望生成后的脚本能保留来源依据，这样我发布前可以快速检查事实。

验收标准：

1. 脚本页展示使用了哪一份资料卡。
2. 脚本页展示资料卡引用来源列表。
3. 关键事实尽量附带来源链接。

## 5. 核心流程

### 5.1 推荐主流程

```text
选题详情
  -> 自动检查资料卡
  -> 无可用资料卡时自动生成/刷新选题资料卡
  -> 本地文章库检索
  -> 判断资料是否足够
  -> 必要时按配置联网搜索补充
  -> LLM 整理资料卡
  -> 用户审阅/编辑资料卡
  -> 生成口播脚本
  -> 生成发布素材包
```

### 5.2 简化首版流程

V0.2.1 先实现：

```text
选题详情
  -> 自动检查资料卡
  -> 本地文章库检索
  -> LLM 生成资料卡
  -> 资料卡进入脚本 prompt
```

V0.3 再增加：

```text
资料不足/过旧/最新主题
  -> 按配置判断是否自动联网搜索
  -> 搜索结果入库
  -> 合并进资料卡
```

### 5.3 自动生成触发规则

资料卡默认自动生成，不要求用户手动点击。

触发时机：

1. 用户进入选题详情页时，系统检查资料卡状态；没有资料卡则后台创建 `generate_research_card` 任务。
2. 用户进入脚本生成页时，系统检查资料卡状态；没有可用资料卡则优先生成资料卡。
3. 用户点击“生成脚本”时，如果资料卡还未生成完成，系统先等待或轮询资料卡任务；资料卡完成后再进入脚本生成。
4. 如果资料卡生成失败，页面提示失败原因，并允许用户选择“直接生成脚本”作为兜底。

复用规则：

1. 同一选题已有资料卡且未过期时，默认复用，不重复生成。
2. 资料卡默认 24 小时内有效。
3. 用户手动编辑过资料卡后，默认不自动覆盖，除非用户点击“刷新资料卡”。
4. 用户多次生成不同脚本版本时，复用同一份资料卡，避免重复搜索和重复消耗 LLM。

刷新规则：

1. 当前选题新增关联文章后，资料卡标记为“建议刷新”。
2. 资料卡超过 24 小时，且选题属于时间敏感主题时，标记为“建议刷新”。
3. 刷新资料卡会生成新版本，不直接覆盖旧版本引用关系。

## 6. 资料充分性判断

系统在生成资料卡前，需要先判断本地资料是否足够。

### 6.1 本地资料足够

满足以下条件时，可以不联网：

1. 至少找到 3 篇相关资料。
2. 至少 1 篇来自 S/A 级来源，或至少 2 篇来自 B 级来源。
3. 最近 14 天内至少有 1 篇相关资料。
4. 资料覆盖选题的核心实体，例如模型名、工具名、框架名、公司名或技术关键词。

### 6.2 需要联网补充

满足任一条件时，建议联网：

1. 本地相关文章少于 3 篇。
2. 最新相关文章超过 30 天。
3. 选题标题包含“最新”、“发布”、“升级”、“刚刚”、“新模型”、“新功能”等时间敏感词。
4. 选题涉及具体产品版本、模型版本、API 变更、价格、开源项目状态。
5. 本地资料只有中文二次传播源，没有官方源或一手技术源。

### 6.3 不允许强制联网的情况

1. 用户关闭联网搜索开关。
2. 没有配置搜索 API Key。
3. 当前任务是重新生成旧脚本，用户明确选择“只用已有资料”。

## 7. 选题资料卡设计

资料卡是脚本生成前的标准中间产物。

### 7.1 字段

```json
{
  "topic_id": 123,
  "research_title": "OpenAI Agents SDK 对效率工作流的影响",
  "research_summary": "3-5 句话总结这个选题为什么值得讲",
  "latest_updates": [
    {
      "point": "最近发生了什么",
      "source_url": "https://example.com",
      "published_at": "2026-07-01",
      "confidence": "high"
    }
  ],
  "core_facts": [
    {
      "claim": "可以被脚本引用的事实",
      "source_url": "https://example.com",
      "confidence": "high"
    }
  ],
  "efficiency_angle": "站在 AI效率教练 人设下，这件事如何帮助观众提升效率",
  "workflow_example": "一个可口播的使用场景或工作流",
  "audience_value": "对 AI 工具新手、内容创作者、小团队或职场人的价值",
  "talking_points": [
    "适合进入正文的观点 1",
    "适合进入正文的观点 2"
  ],
  "risk_notes": [
    "夸大或误解风险",
    "适用边界"
  ],
  "script_hooks": [
    "可用于开头 3 秒的钩子"
  ],
  "copyable_prompt": "可给观众复制使用的一句话提示词或工作流指令",
  "source_quality": {
    "local_source_count": 5,
    "web_source_count": 2,
    "has_official_source": true,
    "freshness": "recent",
    "overall_confidence": "medium"
  }
}
```

### 7.2 字段要求

1. `research_summary` 必须是中文。
2. `core_facts` 至少 3 条，除非资料不足。
3. 每条 `core_facts` 必须有 `source_url`。
4. `efficiency_angle` 必须把技术点转成效率场景。
5. `risk_notes` 必须至少 1 条。
6. `script_hooks` 至少 3 条。
7. `source_quality.overall_confidence` 只能是 `high`、`medium`、`low`。

## 8. 检索策略

### 8.1 本地检索

本地检索使用当前 MySQL 文章库，不引入向量数据库。

检索输入：

1. 选题标题。
2. 选题一句话结论。
3. 选题关键词。
4. 已关联文章标题。
5. 用户手动输入的补充关键词。

检索字段：

1. `articles.title`
2. `articles.summary`
3. `articles.key_points`
4. `articles.content`
5. `sources.name`
6. `sources.level`

排序建议：

1. 来源等级：S > A > B > C。
2. 发布时间越新越靠前。
3. FULLTEXT 匹配分越高越靠前。
4. 已关联到当前选题的文章优先。

### 8.2 联网搜索

联网搜索作为 V0.3 能力，默认关闭。

#### 8.2.1 搜索 Provider 决策

默认 provider：Tavily Search API。

选择原因：

1. Tavily 面向 AI Agent 和 RAG 场景，返回结果更适合作为 LLM 上下文。
2. 支持 Search + Extract 两步法，适合先找 URL、再提取少量正文。
3. 免费档可以支持 MVP 和个人轻量使用。
4. Python 接入成本低，不需要引入浏览器自动化。

当前价格假设（截至 2026-07-03，实际以 Tavily 官方价格页为准）：

1. Researcher 免费档：1,000 API credits / month。
2. 免费档不需要信用卡。
3. Basic Search：每次约 1 credit。
4. Advanced Search：每次约 2 credits。
5. Basic Extract：每成功提取 5 个 URL 约 1 credit。
6. Pay As You Go：约 $0.008 / credit。

首版默认策略：

```text
search_depth = basic
max_results = 10
extract_max_urls = 5
include_raw_content = false
```

说明：首版不直接把 Tavily raw_content 大量塞给 LLM，而是优先取搜索结果标题、URL、摘要，再用受控提取流程拿少量正文。

#### 8.2.2 可选 Provider

后续可以保留 provider 抽象，但 V0.3 只要求实现 Tavily。

```text
tavily   默认实现
serpapi  可选，用于需要 Google organic results 的场景
brave    可选，用于希望使用独立搜索索引的场景
custom   可选，用户自定义 HTTP 搜索 API
```

明确不使用：

```text
bing_search_api
```

原因：Microsoft Bing Search APIs 已于 2025-08-11 退役，不适合作为新功能依赖。

#### 8.2.3 配置项

建议新增环境变量：

```text
WEB_SEARCH_ENABLED=false
WEB_SEARCH_PROVIDER=tavily
TAVILY_API_KEY=
TAVILY_SEARCH_DEPTH=basic
TAVILY_MAX_RESULTS=10
TAVILY_EXTRACT_MAX_URLS=5
TAVILY_MONTHLY_CREDIT_BUDGET=800
TAVILY_PER_TOPIC_CREDIT_BUDGET=3
```

约束：

1. `WEB_SEARCH_ENABLED=false` 时，系统不得发起联网搜索。
2. 没有 `TAVILY_API_KEY` 时，页面只显示本地资料卡能力。
3. 单个选题默认最多消耗 3 credits。
4. 月度预算默认保留 200 credits 安全余量，避免免费额度被用尽。
5. 超过预算时，本次任务失败为可解释错误，不自动重试消耗更多 credits。

#### 8.2.4 搜索来源策略

搜索 API 的范围是公开互联网，但进入资料卡的来源必须经过过滤和分级。

优先来源：

```text
S 级：官方源
OpenAI、Anthropic、Google AI、Microsoft、Meta、Hugging Face、MCP 官方文档、GitHub 官方仓库

A 级：框架/工具源
LangChain、LlamaIndex、CrewAI、AutoGen、Vercel AI SDK、smolagents 等官方博客、文档、GitHub

B 级：研究与开发者社区
arXiv、Papers with Code、GitHub、Hacker News、Reddit、TLDR Tech

C 级：中文二次传播源
机器之心、量子位、InfoQ、少数派、掘金等
```

过滤规则：

1. 官方源优先进入资料卡。
2. 同一事实如果只有 C 级来源，需要降低 confidence。
3. 广告页、营销落地页、无明确作者或来源的聚合页默认过滤。
4. 搜索结果不等于事实依据，必须经过资料卡生成步骤再进入脚本。

搜索查询词由系统生成，最多 5 条：

1. 中文查询：选题标题 + AI Agent。
2. 英文查询：核心实体 + agent / AI workflow / release。
3. 官方查询：核心实体 + docs / blog / announcement。
4. 开发者查询：核心实体 + GitHub / Hacker News。
5. 争议查询：核心实体 + limitation / issue / risk。

搜索结果限制：

1. 每次最多 10 条搜索结果。
2. 每个结果最多抓取正文前 3000 字符。
3. 默认只保留前 5 条进入资料卡生成。
4. URL 去重。
5. 明显低质量、广告页、聚合页可过滤。

## 9. 页面需求

### 9.1 选题详情页

新增区域：选题研究

显示：

1. 当前资料卡状态：未生成、已生成、需要刷新、资料不足。
2. 本地命中资料数量。
3. 是否建议联网补充。
4. 最近一次资料卡生成时间。
5. 使用的来源列表。
6. 自动生成任务状态：未开始、生成中、已完成、失败。

操作：

1. 自动生成资料卡，不要求用户手动点击。
2. 刷新资料卡。
3. 只用本地资料重新生成。
4. 允许联网补充后重新生成。
5. 编辑资料卡。
6. 使用资料卡生成脚本。

### 9.2 脚本生成页

新增显示：

1. 当前使用的资料卡标题。
2. 资料置信度。
3. 来源数量。
4. 关键风险提醒。

新增约束：

1. 如果没有资料卡，点击“生成脚本”时先自动创建资料卡，再进入脚本生成。
2. 如果资料卡生成失败，仍允许用户选择“不使用研究增强，直接生成脚本”。
3. 如果资料卡置信度为 low，生成按钮旁提示“建议先补充资料”。
4. 生成脚本不会重复触发联网搜索，除非资料卡不存在、过期，或用户选择刷新资料卡。

## 10. 数据模型建议

### 10.1 topic_research_cards

```sql
CREATE TABLE topic_research_cards (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  topic_id INT NOT NULL,
  title VARCHAR(255) NOT NULL,
  summary MEDIUMTEXT,
  card_json JSON NOT NULL,
  confidence VARCHAR(16) NOT NULL DEFAULT 'medium',
  local_source_count INT NOT NULL DEFAULT 0,
  web_source_count INT NOT NULL DEFAULT 0,
  has_official_source TINYINT NOT NULL DEFAULT 0,
  generated_by VARCHAR(64) NOT NULL DEFAULT 'llm',
  version INT NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_research_cards_topic FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
);
```

建议索引：

```sql
CREATE INDEX idx_research_cards_topic_id ON topic_research_cards(topic_id);
CREATE INDEX idx_research_cards_updated_at ON topic_research_cards(updated_at);
```

### 10.2 topic_research_sources

```sql
CREATE TABLE topic_research_sources (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  research_card_id INT NOT NULL,
  article_id INT,
  source_url VARCHAR(1024) NOT NULL,
  source_title VARCHAR(512),
  source_name VARCHAR(255),
  source_level VARCHAR(8),
  published_at DATETIME,
  source_type VARCHAR(32) NOT NULL DEFAULT 'local',
  excerpt MEDIUMTEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_research_sources_card FOREIGN KEY (research_card_id) REFERENCES topic_research_cards(id) ON DELETE CASCADE
);
```

`source_type` 可选值：

```text
local
web
manual
```

### 10.3 scripts 表补充

建议给 `scripts` 增加可空字段：

```sql
ALTER TABLE scripts ADD COLUMN research_card_id INT NULL;
```

用途：

1. 记录脚本使用了哪一份资料卡。
2. 支持后续对比“有资料增强”和“无资料增强”的脚本质量。

## 11. Job 类型

新增 job type：

```text
generate_research_card
web_search_for_topic
refresh_research_card
```

建议执行顺序：

1. `generate_research_card`：自动触发，默认先做本地检索和资料卡生成。
2. `web_search_for_topic`：仅当本地资料不足、联网开关开启、API Key 已配置且预算允许时执行。
3. `refresh_research_card`：用户手动刷新或系统标记过期时执行，重新检索并生成新版本资料卡。

约束：

1. 用户点击“生成脚本”不需要先手动创建资料卡。
2. `generate_script` 任务启动前应检查是否已有可用 `research_card_id`。
3. 如果没有可用资料卡，先创建或等待 `generate_research_card`。
4. 如果资料卡任务失败，`generate_script` 可以按用户选择走无资料卡兜底流程。

## 12. LLM Prompt 需求

新增 prompt：

```text
prompts/topic_research_card.md
```

输入：

1. 选题标题。
2. 选题内容卡。
3. 账号人设。
4. 本地检索资料列表。
5. 可选联网搜索资料列表。

输出：

1. 必须是 JSON。
2. 必须符合第 7 节资料卡结构。
3. 不得编造来源 URL。
4. 不确定的信息必须放入 `risk_notes` 或降低 confidence。
5. 必须把技术信息转成效率工作流视角。

脚本生成 prompt 需要补充：

1. 如果存在资料卡，优先引用资料卡中的 `core_facts`、`efficiency_angle`、`workflow_example` 和 `risk_notes`。
2. 不要引用资料卡之外的事实性结论。
3. 开头钩子可以参考 `script_hooks`，但要适配平台和时长。

## 13. 分期计划

### V0.2.1：本地资料卡（已实现）

范围：

1. 新增资料卡数据表。
2. 新增本地资料检索服务。
3. 新增资料卡生成服务。
4. 选题详情页和脚本生成页自动检查/生成资料卡。
5. 脚本生成流程自动接入资料卡。
6. 提供手动刷新资料卡能力。

不做：

1. 联网搜索。
2. 事实校验。
3. 向量检索。

### V0.3：联网搜索补充（已实现）

范围：

1. 增加联网搜索开关。
2. 实现 Tavily Search API provider。
3. 本地资料不足时按配置自动联网补充。
4. 搜索结果保存到资料卡来源表。
5. 资料卡标记 local/web 来源数量。
6. 增加单选题和月度 credit 预算保护。
7. 保留 provider 抽象，但不要求实现 SerpAPI、Brave 或 custom provider。

不做：

1. 绕过开关、API Key 和预算限制的自动联网。
2. 大规模网页抓取。
3. 搜索结果长期全文索引。
4. Tavily 之外的搜索 provider。

### V0.4：可信度增强（部分实现：事实校验已落地，来源可信度评分已实现 credibility_scorer.py，事实冲突提示和脚本事实引用检查待完善）

范围：

1. 来源可信度评分。
2. 事实冲突提示。
3. 官方源优先策略增强。
4. 脚本事实引用检查。

## 14. 成功指标

### 14.1 产品指标

1. 80% 以上脚本生成前有资料卡。
2. 单条脚本平均引用来源不少于 3 个。
3. 用户手动大改脚本的比例下降。
4. 用户从选题到可发布脚本的时间下降。
5. 资料卡生成不增加用户的必需点击步骤。

### 14.2 内容质量指标

1. 脚本正文中至少包含 2 个具体事实或案例。
2. 每条脚本至少包含 1 个效率工作流建议。
3. 每条脚本至少包含 1 个风险或边界提醒。
4. 脚本不出现无来源的具体发布时间、价格、版本号或产品能力断言。

## 15. 验收标准

V0.2.1 完成时应满足（已全部满足）：

1. 进入任一选题详情页或脚本生成页时，系统自动检查资料卡状态。
2. 没有资料卡时，系统自动从本地文章库检索相关资料并生成资料卡。
3. 资料卡保存到数据库。
4. 资料卡包含摘要、关键事实、效率角度、工作流案例、风险提醒、来源质量。
5. 生成脚本时默认使用最新可用资料卡。
6. 脚本页可以看到本次脚本引用的资料卡和来源列表。
7. 资料卡生成失败时，原脚本生成流程仍可作为兜底使用。
8. 用户可以手动刷新资料卡，但刷新不是生成脚本的必需步骤。

V0.3 完成时应满足（已全部满足）：

1. 系统能判断本地资料是否不足。
2. 联网搜索开启、API Key 已配置且预算允许时，系统能自动联网补充。
3. 联网搜索结果可进入资料卡。
4. 用户关闭联网开关后，系统不会发起联网搜索。
5. 未配置 `TAVILY_API_KEY` 时，联网搜索入口不可执行，并给出可理解提示。
6. 单个选题和月度 credit 预算生效，超出预算时不会继续请求 Tavily。
7. 进入资料卡的联网来源经过 S/A/B/C 分级或过滤。

## 16. 风险与缓解

### 风险 1：联网搜索带来不稳定结果

缓解：

1. 联网搜索默认关闭。
2. 搜索结果数量限制。
3. 用户确认后再联网。
4. 来源列表可见、可删除。

### 风险 2：资料卡生成成本增加

缓解：

1. 优先本地检索。
2. 资料卡可复用。
3. 同一选题默认不重复生成，除非用户刷新。
4. 控制输入资料数量和正文长度。

### 风险 3：脚本仍然可能编造事实

缓解：

1. 脚本 prompt 明确只能使用资料卡事实。
2. 具体版本号、发布时间、价格、能力边界必须有来源。
3. 置信度低时页面提示用户审阅。

### 风险 4：Tavily 免费额度被快速消耗

缓解：

1. 联网搜索默认关闭。
2. 每个选题设置 credit 上限。
3. 每月设置 credit 预算上限。
4. 资料卡默认复用，不因重复生成脚本而重复搜索。
5. 超出预算后提示用户升级或等下月额度重置，不自动重试。

## 17. 开放问题

1. 资料卡是否需要版本对比页面？
2. 用户是否需要手动添加外部 URL 到资料卡？
3. 是否要把资料卡作为脚本版本的一部分冻结，避免后续刷新影响旧脚本复盘？
