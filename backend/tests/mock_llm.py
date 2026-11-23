"""本地 mock 的 OpenAI 兼容端点，用于端到端验证请求链路（不写进生产代码）。"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class H(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        if "response_format" in body:
            content = json.dumps(
                {
                    "facts": [
                        {"category": "appointment", "content": "下周三去曼谷出差", "weight": 1.5,
                         "due_at": "2026-11-25"},
                        {"category": "work", "content": "在金边做手机配件生意", "weight": 1.0},
                    ],
                    "interests": [{"topic": "健身", "score": 0.9, "evidence": "聊了两次训练"}],
                    "avoid_topics": ["前任"],
                    "emotion_baseline": "positive",
                    "intimacy": 55,
                    "unfinished_topics": ["说要发我旅行照片"],
                    "key_facts": ["在金边做手机配件生意"],
                }
            )
        else:
            content = "在干嘛呢\n刚下班，累死了"
        resp = {
            "id": "mock",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 20, "total_tokens": 140},
        }
        data = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # 静音
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8791), H).serve_forever()
