import json
import shutil
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app
from config import BASE_DIR


def completion(delta: dict, finish_reason: str) -> bytes:
    chunk = {
        "id": "mock-chat",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()


@unittest.skipUnless(
    shutil.which("node") and (BASE_DIR / "pi-agent/node_modules/@earendil-works/pi-agent-core").is_dir(),
    "需要 Node.js 和本地 Pi 依赖",
)
class ProjectChatTest(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.responses = []
        test = self

        class ModelHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                test.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                code, content_type, body = test.responses.pop(0)
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
        self.addCleanup(server.server_close)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(server.shutdown)
        self.enterContext(patch.dict("os.environ", {"OPENAI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1"}))
        self.enterContext(patch("services.project_chat.get_api_key", return_value="test-key"))
        self.enterContext(patch("services.project_chat.get_llm_settings", return_value={"model": "mock"}))

    def test_queries_project_and_returns_model_reply(self):
        self.responses.extend([
            (200, "text/event-stream", completion({"tool_calls": [{
                "id": "call_list", "index": 0, "type": "function",
                "function": {"name": "list_topics", "arguments": '{"limit": 1, "date_from": "2026-11-21"}'},
            }]}, "tool_calls")),
            (200, "text/event-stream", completion({"content": "选题 #7 得了 95 分。"}, "stop")),
        ])
        with patch("repositories.topics_repo.list_topics", return_value=[{"id": 7, "score": 95}]) as repo:
            response = TestClient(app).post("/assistant/chat", json={"message": "今天得分最高的选题？"})

        self.assertEqual(response.json(), {"ok": True, "reply": "选题 #7 得了 95 分。", "receipts": []})
        repo.assert_called_once_with(status="", q="", limit=1, date_from="2026-11-21", date_to="")
        result = self.requests[1]["messages"][-1]
        self.assertEqual(result["role"], "tool")
        self.assertEqual(json.loads(result["content"])[0]["id"], 7)

    def test_keeps_real_queue_receipt_after_model_reply_fails(self):
        self.responses.extend([
            (200, "text/event-stream", completion({"tool_calls": [{
                "id": "call_script", "index": 0, "type": "function",
                "function": {"name": "generate_script", "arguments": '{"topic_id": 7}'},
            }]}, "tool_calls")),
            (502, "application/json", b'{"error":{"message":"Temporary error"}}'),
        ])
        with (
            patch("repositories.topics_repo.get_topic", return_value={"id": 7}),
            patch("repositories.jobs_repo.list_active_jobs_by_type", return_value=[]),
            patch("repositories.research_cards_repo.get_latest_card_for_topic", return_value=None),
            patch("repositories.research_cards_repo.has_active_research_job", return_value=False),
            patch("repositories.jobs_repo.enqueue", return_value=12) as enqueue,
        ):
            response = TestClient(app).post("/assistant/chat", json={
                "history": [{"role": "assistant", "content": "这里是选题 #7"}],
                "message": "给它写一条脚本",
            }, headers={"Accept": "application/x-ndjson"})

        enqueue.assert_called_once_with("generate_research_card", {"topic_id": 7})
        self.assertEqual(response.headers["content-type"], "application/x-ndjson")
        started, finished, reply = [json.loads(line) for line in response.iter_lines()]
        self.assertEqual(started, {"type": "tool", "id": 1, "label": "提交脚本生成请求", "state": "running"})
        self.assertEqual(finished["type"], "tool")
        self.assertEqual(finished["id"], started["id"])
        self.assertEqual(finished["state"], "done")
        self.assertEqual(finished["detail"], "资料卡任务 #12 已入队")
        self.assertEqual(reply["type"], "reply")
        result = reply["result"]
        self.assertFalse(result["ok"])
        self.assertEqual(result["receipts"], [{"label": "资料卡任务 #12 已入队", "url": "/topics/7/scripts"}])
        self.assertEqual(finished["receipt"], result["receipts"][0])
        self.assertEqual(self.requests[0]["messages"][1]["content"], "这里是选题 #7")
