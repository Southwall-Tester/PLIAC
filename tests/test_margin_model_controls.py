"""Selective LearnMargin update: real adapter/payload contracts, no paid API calls."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent.acceptance_course import build_graph
from learning_agent.course_graph import CourseGraphError
from learnmargin.demo import demo_lesson
from learnmargin.models import APIConfig, GenerateRequest
from learnmargin.provider import Provider, ProviderError
from learnmargin.reasoning import PROFILES
from learnmargin.storage import Store
from pliac import margin


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = patch.object(margin, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write_config(self, **overrides):
        values = dict(base_url="https://api.deepseek.com", model="deepseek-flash", api_key="test-secret")
        values.update(overrides)
        path = self.root / "config/models.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"default": "chosen", "models": {"chosen": values}}), encoding="utf-8")

    def test_file_fields_reach_adapter_and_old_config_keeps_defaults(self):
        self.write_config()
        config = margin.configured_api()
        self.assertIsNone(config.reasoning_effort)
        self.assertEqual(180, config.timeout_seconds)
        self.write_config(reasoning_effort="high", timeout_seconds=420, protocol="responses",
                          vision=False, json_mode=False, other_module_option=True)
        with patch.dict(os.environ, {"LEARNMARGIN_REASONING_EFFORT": "invalid"}):
            config = margin.configured_api()
        self.assertEqual(("high", 420, "responses", False, False),
                         (config.reasoning_effort, config.timeout_seconds, config.protocol,
                          config.vision, config.json_mode))

    def test_environment_fallback_and_invalid_input_do_not_leak_values(self):
        env = dict(LEARNMARGIN_BASE_URL="https://api.deepseek.com", LEARNMARGIN_MODEL="deepseek-flash",
                   LEARNMARGIN_API_KEY="test-secret", LEARNMARGIN_REASONING_EFFORT="none",
                   LEARNMARGIN_TIMEOUT_SECONDS="360", LEARNMARGIN_PROTOCOL="chat_completions")
        with patch.dict(os.environ, env, clear=True):
            config = margin.configured_api()
            self.assertEqual(("none", 360), (config.reasoning_effort, config.timeout_seconds))
            with patch.dict(os.environ, {"LEARNMARGIN_TIMEOUT_SECONDS": "secret-invalid-value"}):
                with self.assertRaises(CourseGraphError) as error:
                    margin.configured_api()
                self.assertEqual(503, error.exception.status_code)
                self.assertNotIn("secret-invalid-value", str(error.exception))

    def test_invalid_or_unsupported_settings_are_actionable(self):
        for overrides, message in [
            ({"timeout_seconds": 601}, "10～600"),
            ({"reasoning_effort": "medium"}, "不支持"),
            ({"base_url": "https://gateway.example/v1", "reasoning_effort": "high"}, "尚未适配"),
            ({"reasoning_effort": "secret-invalid-value"}, "思考档位"),
        ]:
            with self.subTest(overrides=overrides):
                self.write_config(**overrides)
                with self.assertRaises(CourseGraphError) as error:
                    margin.configured_api()
                self.assertIn(message, str(error.exception))
                self.assertNotIn("test-secret", str(error.exception))
                self.assertNotIn("secret-invalid-value", str(error.exception))


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_registered_controls_and_unknown_defaults(self):
        for profile in PROFILES:
            for endpoint in profile["endpoints"]:
                for model in profile["models"]:
                    for protocol in profile["protocols"]:
                        for effort in [None, *[o["value"] for o in profile["options"]]]:
                            with self.subTest(endpoint=endpoint, model=model, protocol=protocol, effort=effort):
                                settings = APIConfig(base_url=endpoint, model=model, protocol=protocol,
                                                     reasoning_effort=effort)
                                async with Provider(settings, transport=httpx.MockTransport(lambda _: None)) as provider:
                                    body = provider._payload("system", "user", [])
                                controls = {k: body[k] for k in ("thinking", "reasoning", "reasoning_effort") if k in body}
                                if effort is None:
                                    expected = {}
                                elif profile["adapter"] == "toggle":
                                    expected = {"thinking": {"type": effort}}
                                elif protocol == "responses":
                                    expected = {"reasoning": {"effort": effort}}
                                elif profile["adapter"] == "deepseek":
                                    expected = ({"thinking": {"type": "disabled"}} if effort == "none" else
                                                {"thinking": {"type": "enabled"}, "reasoning_effort": effort})
                                else:
                                    expected = {"reasoning_effort": effort}
                                self.assertEqual(expected, controls)
                                self.assertEqual(model, body["model"])
        async with Provider(APIConfig(base_url="https://gateway.example/v1", model="custom")) as provider:
            body = provider._payload("system", "user", [])
        self.assertFalse({"thinking", "reasoning", "reasoning_effort"} & body.keys())
        with patch("httpx.AsyncClient", side_effect=AssertionError("must validate before HTTP client")):
            for settings in [APIConfig(reasoning_effort="medium"),
                             APIConfig(base_url="https://gateway.example/v1", reasoning_effort="high"),
                             APIConfig(base_url="https://api.openai.com/v1", model="gpt-6-astra", reasoning_effort="none")]:
                with self.assertRaises(ValueError):
                    Provider(settings)

    async def test_config_to_http_payload_and_connection_token_limit(self):
        for protocol in ("chat_completions", "responses"):
            sent = []
            def respond(request):
                sent.append(json.loads(request.content))
                if protocol == "responses":
                    result = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}]}
                else:
                    result = {"choices": [{"message": {"content": "OK"}}]}
                return httpx.Response(200, json=result)
            with tempfile.TemporaryDirectory() as tmp, patch.object(margin, "ROOT", Path(tmp)):
                path = Path(tmp) / "config/models.json"
                path.parent.mkdir()
                path.write_text(json.dumps(dict(base_url="https://api.openai.com/v1", model="gpt-6.1-sol",
                    api_key="fake", protocol=protocol, reasoning_effort="high", timeout_seconds=360)), encoding="utf-8")
                async with Provider(margin.configured_api(), transport=httpx.MockTransport(respond)) as provider:
                    await provider._request(provider._payload("system", "user", []))
                    await provider.test_connection()
            limit = "max_output_tokens" if protocol == "responses" else "max_completion_tokens"
            self.assertEqual([12000, 256], [body[limit] for body in sent])
            self.assertTrue(all("max_tokens" not in body for body in sent))
            for body in sent:
                self.assertEqual("gpt-6.1-sol", body["model"])
                self.assertEqual({"effort": "high"} if protocol == "responses" else "high",
                                 body.get("reasoning") if protocol == "responses" else body.get("reasoning_effort"))

    async def test_timeout_reports_actual_budget_without_promising_scan_resume(self):
        async with Provider(APIConfig(timeout_seconds=420)) as provider:
            with patch.object(provider, "_request_with_retries", side_effect=httpx.ReadTimeout("private details")):
                with self.assertRaises(ProviderError) as error:
                    await provider._request({})
        self.assertIn("420 秒", str(error.exception))
        self.assertIn("包含服务重试与响应读取", str(error.exception))
        self.assertNotIn("private details", str(error.exception))
        self.assertNotIn("识读", str(error.exception))


class JobDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_failures_retain_stage_and_retry_reuses_lesson_without_stale_error(self):
        class Stub:
            usage = []
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
        docs, origins = margin.materials(build_graph())
        request = GenerateRequest(document_ids=[d.id for d in docs])
        for step, stage in [("lesson", "整理内容总览与学习路线"),
                            ("graph", "生成知识概念及关系"), ("render", "排版详细讲义")]:
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                store = Store(Path(tmp))
                job = dict(id="b"*32, course_id="synthetic", course_version=1, status="queued")
                store.save_job(job)
                async def writer(*args):
                    args[-1]("整理内容总览与学习路线", 24)
                    if step == "lesson":
                        raise ExceptionGroup("group", [ProviderError("合成超时")])
                    return demo_lesson()
                graph = AsyncMock(side_effect=ProviderError("合成超时") if step == "graph" else None, return_value={})
                renderer = AsyncMock(side_effect=RuntimeError("合成排版错误") if step == "render" else None,
                                     return_value={"page_count": 1})
                with patch.object(margin, "Provider", return_value=Stub()), \
                     patch.object(margin, "generate_lesson", side_effect=writer), \
                     patch.object(margin, "generate_map", graph), patch.object(margin, "render_lesson", renderer):
                    await margin.run_job(store, job, request, docs, origins)
                saved = store.job(job["id"])
                self.assertEqual(("failed", stage), (saved["status"], saved["failed_stage"]))
                self.assertTrue(saved["error"].startswith(stage + "："))
                with patch.object(margin, "Provider", return_value=Stub()), \
                     patch.object(margin, "generate_lesson", new=AsyncMock(return_value=demo_lesson())) as retry_writer, \
                     patch.object(margin, "generate_map", new=AsyncMock(return_value={})), \
                     patch.object(margin, "render_lesson", new=AsyncMock(return_value={"page_count": 1})):
                    await margin.run_job(store, job, request, docs, origins)
                self.assertEqual(1 if step == "lesson" else 0, retry_writer.await_count)
                saved = store.job(job["id"])
                self.assertEqual("completed", saved["status"])
                self.assertNotIn("failed_stage", saved)
                self.assertIsNone(saved["error"])
                metadata = (store.directory("jobs", job["id"]) / "generation.json").read_text(encoding="utf-8")
                self.assertIn("49f1f5e", metadata)
                self.assertNotIn("api_key", metadata)


if __name__ == "__main__":
    unittest.main()
