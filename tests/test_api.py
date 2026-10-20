"""注册登录、聊天持久化与 Kimi 模型调用的后端测试。

运行：
    python -m unittest discover -s tests -v

测试环境默认关闭 Kimi 密钥，使用本地回复引擎，不产生外部请求。
需要验证 Kimi 协议时，用 unittest.mock 拦截 requests.post。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from werkzeug.security import check_password_hash

from app import create_app
from services.persona_service import (
    build_persona_prompt,
    normalize_name,
    role_safe_reply,
)

TEST_DIR = Path(__file__).resolve().parent / "_runtime"


class AppTestCase(unittest.TestCase):
    def setUp(self) -> None:
        TEST_DIR.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="case-", dir=TEST_DIR))
        self.db_path = self.temp_dir / "test.db"
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(self.db_path),
                "SECRET_KEY": "test-secret-key",
                "KIMI_API_KEY": "",
                "KIMI_BASE_URL": "https://api.kimi.example/v1",
                "KIMI_MODEL": "test-model",
                "KIMI_MAX_TOKENS": 800,
                "KIMI_FALLBACK_LOCAL": True,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def register(
        self,
        username: str = "小满用户",
        email: str = "user@example.com",
        password: str = "secret123",
        client=None,
    ):
        return (client or self.client).post(
            "/api/auth/register",
            json={"username": username, "email": email, "password": password},
        )

    def login(
        self,
        username: str = "小满用户",
        password: str = "secret123",
        client=None,
    ):
        return (client or self.client).post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )

    def register_and_login(
        self,
        username: str = "小满用户",
        email: str = "user@example.com",
        password: str = "secret123",
        client=None,
    ) -> None:
        register_response = self.register(
            username=username, email=email, password=password, client=client
        )
        self.assertEqual(register_response.status_code, 201)
        login_response = self.login(
            username=username, password=password, client=client
        )
        self.assertEqual(login_response.status_code, 200)

    def send_chat(
        self,
        girl_name: str = "小满",
        girl_char: str = "温柔",
        message: str = "今天有点累",
    ):
        return self.client.post(
            "/api/chat",
            json={
                "girl_name": girl_name,
                "girl_char": girl_char,
                "message": message,
            },
        )

    def table_rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(sql, params).fetchall()
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # 注册 / 登录
    # ------------------------------------------------------------------
    def test_register_login_and_me(self):
        response = self.register(username="Alice_01", email="alice@example.com")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["data"]["user"]["username"], "Alice_01")

        self.assertEqual(self.client.get("/api/auth/me").get_json()["data"]["authenticated"], False)

        wrong = self.login(username="Alice_01", password="wrong-password")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.get_json()["error"]["code"], "INVALID_CREDENTIALS")

        success = self.login(username="Alice_01", password="secret123")
        self.assertEqual(success.status_code, 200)
        me = self.client.get("/api/auth/me").get_json()["data"]
        self.assertTrue(me["authenticated"])
        self.assertEqual(me["user"]["email"], "alice@example.com")

        logout = self.client.post("/api/auth/logout")
        self.assertEqual(logout.status_code, 200)
        me = self.client.get("/api/auth/me").get_json()["data"]
        self.assertFalse(me["authenticated"])

    def test_password_is_hashed_not_plaintext(self):
        self.register(username="HashUser", email="hash@example.com", password="my-secret-123")
        rows = self.table_rows('SELECT username, password FROM "user"')
        self.assertEqual(len(rows), 1)
        stored = rows[0]["password"]
        self.assertNotEqual(stored, "my-secret-123")
        self.assertNotIn("my-secret-123", stored)
        self.assertTrue(check_password_hash(stored, "my-secret-123"))

    def test_register_duplicate_username_and_email(self):
        self.assertEqual(
            self.register(username="SameUser", email="one@example.com").status_code,
            201,
        )
        duplicate_name = self.register(
            username="SameUser", email="two@example.com"
        )
        self.assertEqual(duplicate_name.status_code, 409)
        self.assertEqual(duplicate_name.get_json()["error"]["code"], "USERNAME_EXISTS")

        duplicate_email = self.register(
            username="OtherUser", email="one@example.com"
        )
        self.assertEqual(duplicate_email.status_code, 409)
        self.assertEqual(duplicate_email.get_json()["error"]["code"], "EMAIL_EXISTS")

    def test_register_validation(self):
        bad_username = self.register(username="a", email="a@example.com")
        self.assertEqual(bad_username.status_code, 422)

        bad_email = self.register(username="ValidName", email="not-an-email")
        self.assertEqual(bad_email.status_code, 422)

        short_password = self.register(
            username="ValidName", email="valid@example.com", password="123"
        )
        self.assertEqual(short_password.status_code, 422)

        invalid_chars = self.register(
            username="bad user!", email="bad@example.com"
        )
        self.assertEqual(invalid_chars.status_code, 422)

    def test_protected_endpoints_require_login(self):
        responses = [
            self.client.get("/api/history?girl_name=小满&girl_char=温柔"),
            self.client.post(
                "/api/chat",
                json={"girl_name": "小满", "girl_char": "温柔", "message": "你好"},
            ),
            self.client.get("/api/chat/recent"),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.get_json()["error"]["code"], "AUTH_REQUIRED")

    # ------------------------------------------------------------------
    # 聊天记录持久化与三要素隔离
    # ------------------------------------------------------------------
    def test_chat_saves_both_roles_and_all_required_fields(self):
        self.register_and_login()
        response = self.send_chat(message="今天有点累")
        self.assertEqual(response.status_code, 201)
        data = response.get_json()["data"]
        self.assertEqual(data["mode"], "demo")
        self.assertTrue(data["assistant_message"]["content"])
        self.assertNotIn("作为 AI", data["assistant_message"]["content"])

        rows = self.table_rows(
            """
            SELECT username, girl_name, girl_char, role, content, create_time
            FROM chat_history
            ORDER BY id ASC
            """
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["role"] for row in rows], ["user", "assistant"])
        self.assertEqual(rows[0]["username"], "小满用户")
        self.assertEqual(rows[0]["girl_name"], "小满")
        self.assertEqual(rows[0]["girl_char"], "温柔")
        self.assertEqual(rows[0]["content"], "今天有点累")
        self.assertTrue(rows[0]["create_time"])
        self.assertTrue(rows[1]["create_time"])

    def test_history_loads_only_for_exact_three_part_match(self):
        self.register_and_login()
        self.assertEqual(self.send_chat(girl_name="小满", girl_char="温柔").status_code, 201)
        self.assertEqual(self.send_chat(girl_name="小满", girl_char="温柔").status_code, 201)

        same = self.client.get("/api/history?girl_name=小满&girl_char=温柔").get_json()["data"]
        self.assertEqual(same["total"], 4)
        self.assertEqual([m["role"] for m in same["items"]], ["user", "assistant", "user", "assistant"])

        different_name = self.client.get("/api/history?girl_name=阿梨&girl_char=温柔").get_json()["data"]
        self.assertEqual(different_name["total"], 0)

        different_char = self.client.get("/api/history?girl_name=小满&girl_char=犀利").get_json()["data"]
        self.assertEqual(different_char["total"], 0)

        # 新组合自己的消息独立保存。
        self.assertEqual(self.send_chat(girl_name="小满", girl_char="犀利").status_code, 201)
        new_pair = self.client.get("/api/history?girl_name=小满&girl_char=犀利").get_json()["data"]
        self.assertEqual(new_pair["total"], 2)
        original = self.client.get("/api/history?girl_name=小满&girl_char=温柔").get_json()["data"]
        self.assertEqual(original["total"], 4)

    def test_changing_only_personality_starts_empty_chat(self):
        self.register_and_login()
        self.send_chat(girl_name="晚晚", girl_char="温柔")
        response = self.client.get("/api/history?girl_name=晚晚&girl_char=暴躁")
        data = response.get_json()["data"]
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["persona"]["girl_char"], "暴躁")

    def test_same_name_and_personality_from_another_user_is_isolated(self):
        self.register_and_login(username="user_one", email="one@example.com")
        self.send_chat(girl_name="小满", girl_char="温柔")

        second = self.app.test_client()
        self.register_and_login(
            username="user_two",
            email="two@example.com",
            client=second,
        )
        second_history = second.get("/api/history?girl_name=小满&girl_char=温柔").get_json()["data"]
        self.assertEqual(second_history["total"], 0)
        self.assertEqual(second.post(
            "/api/chat",
            json={"girl_name": "小满", "girl_char": "温柔", "message": "第二条故事"},
        ).status_code, 201)
        second_history = second.get("/api/history?girl_name=小满&girl_char=温柔").get_json()["data"]
        self.assertEqual(second_history["total"], 2)

        first_history = self.client.get("/api/history?girl_name=小满&girl_char=温柔").get_json()["data"]
        self.assertEqual(first_history["total"], 2)
        self.assertNotEqual(
            first_history["items"][0]["content"],
            second_history["items"][0]["content"],
        )

    def test_history_endpoint_returns_all_messages(self):
        self.register_and_login()
        for index in range(16):
            response = self.send_chat(message=f"第 {index + 1} 条消息")
            self.assertEqual(response.status_code, 201)
        history = self.client.get("/api/history?girl_name=小满&girl_char=温柔").get_json()["data"]
        self.assertEqual(history["total"], 32)
        self.assertEqual(len(history["items"]), 32)
        self.assertEqual(history["items"][0]["content"], "第 1 条消息")

    def test_recent_persona_uses_latest_triple(self):
        self.register_and_login()
        empty = self.client.get("/api/chat/recent").get_json()["data"]
        self.assertIsNone(empty["persona"])

        self.send_chat(girl_name="小满", girl_char="温柔")
        self.send_chat(girl_name="晚晚", girl_char="犀利")
        recent = self.client.get("/api/chat/recent").get_json()["data"]["persona"]
        self.assertEqual(recent["girl_name"], "晚晚")
        self.assertEqual(recent["girl_char"], "犀利")
        self.assertEqual(recent["message_count"], 2)

    def test_accepts_personality_code_and_returns_chinese_label(self):
        self.register_and_login()
        response = self.send_chat(girl_name="小满", girl_char="gentle")
        self.assertEqual(response.status_code, 201)
        data = response.get_json()["data"]
        self.assertEqual(data["persona"]["girl_char"], "温柔")
        history = self.client.get("/api/history?girl_name=小满&girl_char=温柔").get_json()["data"]
        self.assertEqual(history["total"], 2)

    def test_chat_validation(self):
        self.register_and_login()
        self.assertEqual(self.send_chat(girl_name="", girl_char="温柔").status_code, 422)
        self.assertEqual(self.send_chat(girl_name="一二三四五六七八九十一", girl_char="温柔").status_code, 422)
        self.assertEqual(self.send_chat(girl_name="小满", girl_char="不存在").status_code, 422)
        self.assertEqual(self.send_chat(message="   ").status_code, 422)
        self.assertEqual(self.send_chat(message="长" * 2001).status_code, 422)

    # ------------------------------------------------------------------
    # Kimi Chat Completions API
    # ------------------------------------------------------------------
    def enable_kimi(self, fallback: bool = True) -> None:
        self.app.config.update(
            {
                "KIMI_API_KEY": "test-kimi-key",
                "KIMI_BASE_URL": "https://api.kimi.example/v1",
                "KIMI_MODEL": "kimi-test-model",
                "KIMI_MAX_TOKENS": 800,
                "KIMI_FALLBACK_LOCAL": fallback,
            }
        )

    @patch("services.llm_service.requests.post")
    def test_kimi_request_payload_and_response_parsing(self, mock_post):
        self.register_and_login()
        self.send_chat(message="第一轮旧消息")  # 先写入一条本地历史

        self.enable_kimi()
        upstream = Mock(status_code=200)
        upstream.json.return_value = {
            "id": "chatcmpl_test",
            "model": "kimi-test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "我在呢。先过来坐一会儿吧。",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        }
        mock_post.return_value = upstream

        response = self.send_chat(message="第二轮新消息")
        self.assertEqual(response.status_code, 201)
        data = response.get_json()["data"]
        self.assertEqual(data["mode"], "kimi")
        self.assertEqual(
            data["assistant_message"]["content"], "我在呢。先过来坐一会儿吧。"
        )

        call = mock_post.call_args
        self.assertEqual(
            call.args[0], "https://api.kimi.example/v1/chat/completions"
        )
        headers = call.kwargs["headers"]
        self.assertTrue(headers["Authorization"].startswith("Bearer "))
        payload = call.kwargs["json"]
        self.assertEqual(payload["model"], "kimi-test-model")
        self.assertEqual(payload["max_tokens"], 800)
        self.assertNotIn("temperature", payload)
        self.assertFalse(payload["stream"])

        messages = payload["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("小满", messages[0]["content"])
        self.assertIn("不要跳出角色", messages[0]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "第二轮新消息"})
        assistant_turns = [item for item in messages if item["role"] == "assistant"]
        self.assertEqual(len(assistant_turns), 1)
        self.assertIn("第一轮旧消息", [m["content"] for m in messages])
        self.assertEqual(
            sum(
                1
                for item in messages
                if item["role"] == "user" and item["content"] == "第二轮新消息"
            ),
            1,
        )

        history = self.client.get(
            "/api/history?girl_name=小满&girl_char=温柔"
        ).get_json()["data"]
        self.assertEqual(history["total"], 4)

    @patch("services.llm_service.requests.post")
    def test_kimi_model_unavailable_falls_back_and_persists(self, mock_post):
        self.enable_kimi(fallback=True)
        self.register_and_login()
        upstream = Mock(status_code=404, text='{"error":{"message":"model not found"}}')
        upstream.json.return_value = {"error": {"message": "model not found"}}
        mock_post.return_value = upstream

        response = self.send_chat(message="模型不可用时也要能聊")
        self.assertEqual(response.status_code, 201)
        data = response.get_json()["data"]
        self.assertEqual(data["mode"], "fallback")
        self.assertIn("本地角色", data["notice"])
        self.assertTrue(data["assistant_message"]["content"])

        history = self.client.get(
            "/api/history?girl_name=小满&girl_char=温柔"
        ).get_json()["data"]
        self.assertEqual(history["total"], 2)

    @patch("services.llm_service.requests.post")
    def test_kimi_failure_without_fallback_does_not_save_half_round(self, mock_post):
        self.enable_kimi(fallback=False)
        self.register_and_login()
        upstream = Mock(status_code=500, text="upstream error")
        upstream.json.side_effect = ValueError("not json")
        mock_post.return_value = upstream

        response = self.send_chat(message="不应写进数据库")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["error"]["code"], "KIMI_UPSTREAM_ERROR")
        history = self.client.get(
            "/api/history?girl_name=小满&girl_char=温柔"
        ).get_json()["data"]
        self.assertEqual(history["total"], 0)

    @patch("services.llm_service.requests.post")
    def test_kimi_empty_output_falls_back(self, mock_post):
        self.enable_kimi(fallback=True)
        self.register_and_login()
        upstream = Mock(status_code=200)
        upstream.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": ""}}]
        }
        mock_post.return_value = upstream

        response = self.send_chat(message="空回复测试")
        self.assertEqual(response.status_code, 201)
        data = response.get_json()["data"]
        self.assertEqual(data["mode"], "fallback")
        self.assertTrue(data["assistant_message"]["content"])


class PersonaPromptTestCase(unittest.TestCase):
    def test_prompt_contains_role_lock_and_persona(self):
        prompt = build_persona_prompt("小满", "gentle")
        self.assertIn("你叫「小满」", prompt)
        self.assertIn("温柔", prompt)
        self.assertIn("不要跳出角色", prompt)
        self.assertIn("不要自称 AI", prompt)
        self.assertIn("不可打破的规则", prompt)

    def test_name_normalization(self):
        with self.assertRaises(Exception):
            normalize_name("一二三四五六七八九十一")
        with self.assertRaises(Exception):
            normalize_name("小<满")
        self.assertEqual(normalize_name("  小   满  "), "小 满")

    def test_role_guard_rewrites_out_of_character_reply(self):
        safe = role_safe_reply("作为 AI 语言模型，我无法感受情绪。", "小满", "gentle")
        self.assertNotIn("AI", safe)
        self.assertNotIn("语言模型", safe)
        self.assertTrue(safe)
        self.assertEqual(
            role_safe_reply("我在呢。今天过得怎么样？", "小满", "gentle"),
            "我在呢。今天过得怎么样？",
        )


if __name__ == "__main__":
    unittest.main()
