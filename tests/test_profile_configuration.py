import unittest
from pathlib import Path
from unittest.mock import patch

from services.llm import get_profile_context


ROOT = Path(__file__).resolve().parents[1]


class ProfileConfigurationTest(unittest.TestCase):
    @patch("services.llm.get_profile")
    def test_profile_context_uses_configured_name(self, get_profile):
        get_profile.return_value = {
            "name": "独立开发顾问",
            "positioning": "帮小团队验证产品想法",
            "target_audience": "独立开发者",
            "tone": "坦诚、简洁",
            "content_boundary": "不做增长神话",
            "default_cta": "留言说说你正在验证什么",
        }
        context = get_profile_context()
        self.assertIn("你是「独立开发顾问」", context)
        self.assertIn("帮小团队验证产品想法", context)
        self.assertNotIn("AI效率教练", context)

    def test_runtime_prompts_and_services_do_not_hardcode_default_profile_name(self):
        checked = []
        for folder in ("prompts", "services", "templates"):
            for path in (ROOT / folder).rglob("*"):
                if path.suffix not in {".md", ".py", ".html"}:
                    continue
                checked.append(path)
                self.assertNotIn(
                    "AI效率教练",
                    path.read_text(encoding="utf-8"),
                    f"{path.relative_to(ROOT)} 不应写死默认人设名称",
                )
        self.assertTrue(checked)


if __name__ == "__main__":
    unittest.main()
