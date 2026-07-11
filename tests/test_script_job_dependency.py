import unittest
from unittest.mock import patch

import app


class ScriptJobDependencyTest(unittest.TestCase):
    @patch("repositories.jobs_repo.enqueue")
    @patch("repositories.research_cards_repo.has_active_research_job", return_value=True)
    @patch("repositories.research_cards_repo.get_latest_card_for_topic", return_value=None)
    @patch("repositories.jobs_repo.list_active_jobs_by_type", return_value=[])
    def test_active_research_job_prevents_script_enqueue(
        self, _active_scripts, _latest_card, _active_research, enqueue
    ):
        response = app.script_generate(
            topic_id=7, platform="douyin", format="工具教程", duration=90
        )
        self.assertEqual(response.status_code, 303)
        enqueue.assert_not_called()

    @patch("repositories.jobs_repo.enqueue")
    @patch("repositories.research_cards_repo.has_active_research_job", return_value=False)
    @patch("repositories.research_cards_repo.get_latest_card_for_topic", return_value=None)
    @patch("repositories.jobs_repo.list_active_jobs_by_type", return_value=[])
    def test_missing_research_card_enqueues_only_research_job(
        self, _active_scripts, _latest_card, _active_research, enqueue
    ):
        response = app.script_generate(
            topic_id=7, platform="douyin", format="工具教程", duration=90
        )
        self.assertEqual(response.status_code, 303)
        enqueue.assert_called_once_with("generate_research_card", {"topic_id": 7})


if __name__ == "__main__":
    unittest.main()
