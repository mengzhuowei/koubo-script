import unittest
from unittest.mock import Mock, patch

import services.llm as llm


class LLMClientTest(unittest.TestCase):
    def setUp(self):
        llm._client_cache = None

    def tearDown(self):
        llm._client_cache = None

    @patch("services.llm.OpenAI")
    @patch("services.llm.get_api_key", return_value="test-key")
    def test_build_client_uses_configured_base_url(self, _get_api_key, openai):
        client = Mock()
        openai.return_value = client

        with patch.dict(
            "os.environ",
            {"OPENAI_BASE_URL": "https://llm.example.com/v1"},
            clear=False,
        ):
            self.assertIs(llm._build_client(), client)

        openai.assert_called_once_with(
            api_key="test-key",
            base_url="https://llm.example.com/v1",
        )

    @patch("services.llm.OpenAI")
    @patch("services.llm.get_api_key", return_value="test-key")
    def test_build_client_defaults_to_openai_base_url(self, _get_api_key, openai):
        with patch.dict("os.environ", {}, clear=True):
            llm._build_client()

        openai.assert_called_once_with(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
        )

    @patch("services.llm.OpenAI")
    @patch("services.llm.get_api_key", return_value="test-key")
    def test_client_cache_is_invalidated_when_base_url_changes(self, _get_api_key, openai):
        openai.side_effect = [Mock(), Mock()]

        with patch.dict("os.environ", {"OPENAI_BASE_URL": "https://one.example/v1"}):
            first = llm._build_client()
            self.assertIs(llm._build_client(), first)

        with patch.dict("os.environ", {"OPENAI_BASE_URL": "https://two.example/v1"}):
            second = llm._build_client()

        self.assertIsNot(first, second)
        self.assertEqual(openai.call_count, 2)


if __name__ == "__main__":
    unittest.main()
