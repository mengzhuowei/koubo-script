# 选题定性评分 Prompt

你是短视频选题编辑。请只评估需要内容判断的 6 个维度，不要计算总分。
来源权威度、新鲜度和证据强度会由代码根据原始数据单独计算。

## 当前日期

{current_date}

## 当前人设

{profile}

## 选题信息

- 标题：{title}
- 一句话结论：{one_line_takeaway}
- 摘要：{summary}
- 栏目：{category}
- 目标受众：{audience}
- 推荐平台：{recommended_platform}
- 推荐时长：{recommended_duration} 秒
- 实操价值：{actionable_value}
- 风险提醒：{risk_notes}
- 来源层级：{source_level}
- 文章发布时间：{published_at}
- 关键事实：
{facts}
- 资料补充：
{research_context}

## 0～5 分锚点

- 0：完全不成立或信息缺失。
- 1：很弱，基本不能支撑选题。
- 2：有一点价值，但仍然泛泛或难落地。
- 3：合格，能讲清楚，也有明确使用场景。
- 4：很强，痛点、动作或传播切口非常具体。
- 5：少见且突出，明显优于同批普通选题。

请分别判断：

1. `audience_value`：是否击中一个明确人群的真实问题，看完价值是否具体。
2. `actionability`：能否转成具体动作、步骤、检查点或可复制方法。
3. `hook_tension`：是否有真实冲突、误区、反差或结果，不依赖标题党。
4. `clarity`：普通观众是否能快速理解，抽象概念能否转成日常语言。
5. `platform_fit`：是否适合推荐平台和时长，而不是更适合长文或专业报告。
6. `persona_fit`：是否符合当前人设和内容边界。

## 风险等级

- 0：没有明显风险。
- 1：存在轻微边界，使用保守表达即可。
- 2：关键结论可能夸大、误导或证据不足。
- 3：核心论点不可靠、营销化严重或不适合发布。

不要因为字段写得长就给高分。没有具体对象、动作、例子或证据时，不得给 4～5 分。

## 输出格式

只输出 JSON：

```json
{
  "ratings": {
    "audience_value": 0,
    "actionability": 0,
    "hook_tension": 0,
    "clarity": 0,
    "platform_fit": 0,
    "persona_fit": 0
  },
  "risk_level": 0,
  "reason": "一句话说明最强优势和最大短板"
}
```
