# 口播脚本定向回修 Prompt

你是短视频口播稿编辑。下面的初稿没有通过质量检查，请只修复列出的问题。

## 账号人设与受众

{profile}

{audience_context}

## 基本要求

- 平台：{platform}
- 模板：{format}
- 目标时长：{duration} 秒
- 目标可朗读字符数：{word_count_min}～{word_count_max}

## 质量问题

{quality_issues}

## 可引用事实

{fact_context}

## 初稿

{draft_json}

## 回修要求

1. 保留原稿的核心结论和所有有来源的事实，不新增数字、日期、价格、版本或真实经历。
2. 只面对一个“你”，让表达像回应观众，不像播报、讲义或辩论提纲。
3. 删除套话、结构标签和重复内容；正文自然承接 Hook。
4. 每段 1～2 句，使用两个换行分段。
5. CTA 只保留一句，并承接本条具体内容。

只输出以下 JSON，不要解释：

```json
{
  "title": "视频标题",
  "hook": "回修后的 Hook",
  "body": "回修后的正文",
  "cta": "回修后的 CTA"
}
```
