import unittest

from services.script_generator import (
    ScriptPayload,
    _build_audience_context,
    _build_duration_instructions,
    _build_research_context,
    _parse_payload,
    _quality_issues,
    _spoken_char_count,
    _validate_options,
    _word_count_range,
)


class ScriptGeneratorHelpersTest(unittest.TestCase):
    def test_spoken_char_count_excludes_punctuation_and_whitespace(self):
        self.assertEqual(_spoken_char_count("你好，AI Agent！\nGPT-4"), 13)

    def test_word_count_range_uses_chatty_pacing(self):
        self.assertEqual(_word_count_range(60), (240, 300))

    def test_audience_context_locks_first_topic_audience(self):
        topic = {
            "audience_list": ["AI 工具新手", "独立开发者"],
            "actionable_value": "学会先做小范围检查",
        }
        card = {"card": {
            "audience_value": "减少返工",
            "workflow_example": "先预览再执行",
        }}
        context = _build_audience_context(topic, card)
        self.assertIn("核心观众：AI 工具新手", context)
        self.assertNotIn("独立开发者", context)
        self.assertIn("减少返工", context)

    def test_research_context_routes_fields_by_format(self):
        card = {"card": {
            "latest_updates": [{
                "point": "工具发布新版本",
                "source_url": "https://example.com",
                "published_at": "2026-07-01",
            }],
            "workflow_example": "打开设置并检查结果",
            "copyable_prompt": "先给我一个预览",
            "talking_points": ["不要把自动化等同于无人监管"],
            "script_hooks": ["不应进入上下文的现成钩子"],
            "core_facts": [],
            "risk_notes": [],
        }}
        hot = _build_research_context(card, "热点解读")
        tutorial = _build_research_context(card, "工具教程")
        opinion = _build_research_context(card, "观点拆解")
        self.assertIn("工具发布新版本", hot)
        self.assertNotIn("先给我一个预览", hot)
        self.assertIn("先给我一个预览", tutorial)
        self.assertIn("不要把自动化", opinion)
        self.assertNotIn("现成钩子", hot + tutorial + opinion)

    def test_duration_budget_changes_with_length_and_format(self):
        self.assertIn("三个操作步骤", _build_duration_instructions(60, "工具教程"))
        self.assertIn("一个完整案例", _build_duration_instructions(180, "观点拆解"))

    def test_payload_schema_rejects_missing_body(self):
        payload, issue = _parse_payload({"title": "标题", "hook": "开头", "cta": "结尾"})
        self.assertIsNone(payload)
        self.assertIn("body", issue)

    def test_quality_check_detects_broadcast_style_and_labels(self):
        payload = ScriptPayload(
            title="测试",
            hook="今天给大家分享一个方法",
            body="正文：先做第一步。",
            cta="关注我",
        )
        issues = _quality_issues(
            payload, platform="douyin", duration=10,
            word_count_min=1, word_count_max=100,
        )
        joined = "；".join(issues)
        self.assertIn("套话", joined)
        self.assertIn("结构标签", joined)
        self.assertIn("使用“你”", joined)

    def test_generation_options_are_validated(self):
        _validate_options(platform="douyin", fmt="工具教程", duration=90)
        with self.assertRaises(ValueError):
            _validate_options(platform="video", fmt="工具教程", duration=90)
        with self.assertRaises(ValueError):
            _validate_options(platform="douyin", fmt="工具教程", duration=5)


if __name__ == "__main__":
    unittest.main()
