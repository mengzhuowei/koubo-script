import unittest
from unittest.mock import patch

from services.project_suggestions import SuggestionRequest, suggestions


class ProjectSuggestionTest(unittest.TestCase):
    @patch("services.project_suggestions.sample", return_value=["topics", "sources", "failed_jobs"])
    @patch("services.project_suggestions.chat_json", return_value={
        "prompts": {"topics": "挑出今天最值得看的三个选题", "unknown": "打开另一个应用"},
    })
    def test_starters_accept_model_variation_for_selected_actions(self, _model, _sample):
        result = suggestions(SuggestionRequest())
        self.assertEqual(result["starters"], [
            "挑出今天最值得看的三个选题", "列出最近抓取过的来源", "查一下最近失败的后台任务",
        ])

    @patch("services.project_suggestions.chat_json", return_value={"next_prompt": "查看任务 #12 的状态"})
    def test_followup_uses_last_turn_and_actual_receipt(self, model):
        result = suggestions(SuggestionRequest(message="生成今日选题", reply="已提交", receipts=["任务 #12 已入队"]))
        self.assertEqual(result["next_prompt"], "查看任务 #12 的状态")
        context = model.call_args.args[0][1]["content"]
        self.assertIn("任务 #12 已入队", context)
        self.assertIn("生成今日选题", context)
        self.assertNotIn("read_attachment", context)
