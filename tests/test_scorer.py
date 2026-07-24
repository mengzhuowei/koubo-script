import unittest
from datetime import datetime
from unittest.mock import patch

from services.scorer import (
    DEFAULT_WEIGHTS,
    SCORE_VERSION,
    WEIGHT_PROFILES,
    QualitativeAssessment,
    QualitativeRatings,
    _compose_score,
    _fallback_assessment,
    _parse_datetime,
    score_topic,
)


def _card(category: str = "AI效率快报") -> dict:
    return {
        "title": "这个 Agent 功能为什么会让你返工？",
        "one_line_takeaway": "先预览再执行，能减少自动化返工。",
        "summary": "一个面向独立开发者的具体工作流，解释如何在执行前检查变更。",
        "category": category,
        "audience": ["独立开发者"],
        "recommended_platform": "douyin",
        "recommended_duration": 60,
        "actionable_value": "打开预览，检查变更范围，再确认执行。",
        "risk_notes": "",
        "key_facts": [{
            "claim": "产品提供执行前预览",
            "source_url": "https://example.com/docs",
        }],
    }


def _assessment(rating: float = 3, risk_level: int = 0) -> QualitativeAssessment:
    return QualitativeAssessment(
        ratings=QualitativeRatings(
            audience_value=rating,
            actionability=rating,
            hook_tension=rating,
            clarity=rating,
            platform_fit=rating,
            persona_fit=rating,
        ),
        risk_level=risk_level,
        reason="价值明确，但仍需更多案例。",
    )


class TopicScorerTest(unittest.TestCase):
    def test_every_weight_profile_totals_100(self):
        self.assertEqual(sum(DEFAULT_WEIGHTS.values()), 100)
        for name, weights in WEIGHT_PROFILES.items():
            with self.subTest(name=name):
                self.assertEqual(sum(weights.values()), 100)

    def test_rule_fallback_is_conservative_instead_of_saturating(self):
        card = _card()
        result = _compose_score(
            article={"source_level": "A", "published_at": datetime.now()},
            card=card,
            assessment=_fallback_assessment(card),
            method="hybrid_rule",
            stage="provisional",
            sources=[{
                "source_level": "A",
                "published_at": datetime.now(),
                "source_url": "https://example.com/docs",
            }],
        )
        self.assertLess(result.score, 85)
        self.assertEqual(result.confidence, "low")

    def test_high_risk_deducts_15_points(self):
        base = dict(
            article={"source_level": "A", "published_at": datetime.now()},
            card=_card(),
            method="hybrid_llm",
            stage="final",
            sources=[],
        )
        safe = _compose_score(assessment=_assessment(risk_level=0), **base)
        risky = _compose_score(assessment=_assessment(risk_level=3), **base)
        self.assertEqual(safe.score - risky.score, 15)
        self.assertEqual(risky.breakdown["risk_penalty"], 15)

    @patch("services.scorer.chat_json")
    def test_llm_only_rates_dimensions_and_code_builds_total(self, chat_json):
        chat_json.return_value = {
            "ratings": {
                "audience_value": 4,
                "actionability": 4,
                "hook_tension": 3,
                "clarity": 4,
                "platform_fit": 4,
                "persona_fit": 3,
            },
            "risk_level": 1,
            "reason": "实操价值强，但传播冲突一般。",
        }
        result = score_topic(
            {"source_level": "A", "published_at": datetime.now()},
            _card(),
            sources=[{
                "source_level": "A",
                "published_at": datetime.now(),
                "source_url": "https://example.com/docs",
            }],
        )
        self.assertEqual(result.method, "hybrid_llm")
        self.assertEqual(result.version, SCORE_VERSION)
        self.assertEqual(result.breakdown["risk_penalty"], 3)
        self.assertIn("evidence_strength", result.breakdown["dimensions"])
        self.assertNotEqual(result.score, chat_json.return_value.get("score"))

    def test_timezone_and_database_datetimes_can_be_compared(self):
        aware = _parse_datetime("2026-07-25T08:00:00+08:00")
        naive = _parse_datetime("2026-07-25 00:00:00")
        self.assertIsNone(aware.tzinfo)
        self.assertEqual(aware, naive)


if __name__ == "__main__":
    unittest.main()
