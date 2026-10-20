"""Bounded recovery from explicit API output limits; no live model calls."""
import json
from pathlib import Path
import sys
import unittest

import httpx
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learnmargin.models import APIConfig
from learnmargin.provider import Provider, ProviderError


class Result(BaseModel):
    answer: str


def response_body(protocol, *, limit=False, filtered=False, refused=False, text='{"answer":"complete"}'):
    if protocol == "responses":
        result = {
            "status": "incomplete" if limit or filtered else "completed",
            "output": [{"type": "message", "content": [
                {"type": "refusal", "refusal": "private refusal"} if refused else
                {"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 12, "output_tokens": 12000 if limit else 20,
                      "output_tokens_details": {"reasoning_tokens": 8}},
        }
        if limit or filtered:
            result["incomplete_details"] = {"reason": "max_output_tokens" if limit else "content_filter"}
        return result
    return {
        "choices": [{"finish_reason": "length" if limit else "content_filter" if filtered else "stop",
                     "message": {"content": text, **({"refusal": "private refusal"} if refused else {})}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 12000 if limit else 20,
                  "completion_tokens_details": {"reasoning_tokens": 8}},
    }


class TruncationTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, protocol, *, reasoning=False):
        values = dict(protocol=protocol, base_url="https://gateway.example/v1", model="synthetic")
        if reasoning:
            values.update(base_url="https://api.openai.com/v1", model="gpt-6.1-sol", reasoning_effort="high")
        return APIConfig(**values)

    def transport(self, responses, sent):
        def respond(request):
            sent.append(json.loads(request.content))
            value = responses[len(sent) - 1]
            return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
        return httpx.MockTransport(respond)

    async def test_normal_output_uses_one_request_and_safe_telemetry(self):
        for protocol in ("chat_completions", "responses"):
            with self.subTest(protocol=protocol):
                sent, body = [], response_body(protocol)
                body["usage"].update(secret_text="private", secret_count=3,
                                     total_tokens=float("inf"), prompt_cache_hit_tokens=True,
                                     prompt_cache_miss_tokens=-1)
                # HTTPX's JSON encoder rejects non-finite values, as a real API should.
                body["usage"].pop("total_tokens")
                async with Provider(self.settings(protocol), transport=self.transport([body], sent)) as provider:
                    result = await provider.generate(Result, "system", "user")
                    usage = provider.usage
                self.assertEqual("complete", result.answer)
                self.assertEqual(1, len(sent))
                self.assertEqual(12000, usage[0]["requested_output_tokens"])
                self.assertEqual(8, usage[0]["reasoning_tokens"])
                self.assertFalse({"secret_text", "secret_count", "prompt_cache_hit_tokens",
                                  "prompt_cache_miss_tokens"} & usage[0].keys())
                self.assertNotIn("private", json.dumps(usage))

    async def test_explicit_limits_expand_once_across_protocols_and_reasoning_fields(self):
        for protocol, reasoning in (("chat_completions", False), ("chat_completions", True),
                                    ("responses", False), ("responses", True)):
            with self.subTest(protocol=protocol, reasoning=reasoning):
                sent = []
                replies = [response_body(protocol, limit=True, text='{"answer":"partial'),
                           response_body(protocol)]
                async with Provider(self.settings(protocol, reasoning=reasoning),
                                    transport=self.transport(replies, sent)) as provider:
                    result = await provider.generate(Result, "system", "user")
                    usage = provider.usage
                key = "max_output_tokens" if protocol == "responses" else "max_completion_tokens" if reasoning else "max_tokens"
                self.assertEqual([12000, 24000], [p[key] for p in sent])
                self.assertEqual("complete", result.answer)
                self.assertEqual([12000, 24000], [u["requested_output_tokens"] for u in usage])
                self.assertEqual("max_output_tokens" if protocol == "responses" else "length",
                                 usage[0]["incomplete_reason" if protocol == "responses" else "finish_reason"])
                if reasoning:
                    self.assertEqual({"effort": "high"} if protocol == "responses" else "high",
                                     sent[1]["reasoning" if protocol == "responses" else "reasoning_effort"])
                # The incomplete JSON is discarded, never used as a new instruction.
                self.assertNotIn("partial", json.dumps(sent))

    async def test_second_length_limit_stops_at_two_requests(self):
        for protocol in ("chat_completions", "responses"):
            with self.subTest(protocol=protocol):
                sent = []
                replies = [response_body(protocol, limit=True)] * 2
                async with Provider(self.settings(protocol), transport=self.transport(replies, sent)) as provider:
                    with self.assertRaises(ProviderError) as error:
                        await provider.generate(Result, "system", "user")
                self.assertEqual(2, len(sent))
                self.assertIn("12000", str(error.exception))
                self.assertIn("24000", str(error.exception))
                self.assertIn("仍达到长度上限", str(error.exception))

    async def test_filters_and_refusals_are_not_retried(self):
        for protocol in ("chat_completions", "responses"):
            for kind in ("filtered", "refused"):
                with self.subTest(protocol=protocol, kind=kind):
                    sent = []
                    async with Provider(self.settings(protocol), transport=self.transport(
                            [response_body(protocol, **{kind: True})], sent)) as provider:
                        with self.assertRaises(ProviderError) as error:
                            await provider.generate(Result, "system", "user")
                    self.assertEqual(1, len(sent))
                    self.assertIn("内容过滤" if kind == "filtered" else "拒绝", str(error.exception))
                    self.assertNotIn("private", str(error.exception))
                    self.assertNotIn("长度上限", str(error.exception))

    async def test_unknown_incomplete_or_failed_status_never_increases_budget(self):
        for status, details in (("incomplete", {"reason": "private"}),
                                ("incomplete", ["max_output_tokens"]), ("failed", None), ("cancelled", None)):
            with self.subTest(status=status, details=details):
                sent = []
                body = response_body("responses")
                body.update(status=status, incomplete_details=details)
                async with Provider(self.settings("responses"), transport=self.transport([body], sent)) as provider:
                    with self.assertRaises(ProviderError) as error:
                        await provider.generate(Result, "system", "user")
                    self.assertNotIn("private", json.dumps(provider.usage))
                self.assertEqual(1, len(sent))
                self.assertNotIn("private", str(error.exception))

    async def test_schema_repair_and_length_recovery_share_three_request_bound(self):
        for protocol in ("chat_completions", "responses"):
            for limit_first in (False, True):
                with self.subTest(protocol=protocol, limit_first=limit_first):
                    sent = []
                    limited = response_body(protocol, limit=True)
                    invalid = response_body(protocol, text="{}")
                    replies = [limited, invalid] if limit_first else [invalid, limited]
                    replies.append(response_body(protocol))
                    async with Provider(self.settings(protocol), transport=self.transport(replies, sent)) as provider:
                        result = await provider.generate(Result, "system", "user")
                    self.assertEqual("complete", result.answer)
                    key = "max_output_tokens" if protocol == "responses" else "max_tokens"
                    self.assertEqual([12000, 24000 if limit_first else 12000, 24000], [p[key] for p in sent])
                    final_prompt = sent[-1]["input"][0]["content"][0]["text"] if protocol == "responses" else sent[-1]["messages"][1]["content"]
                    self.assertIn("缺少必填字段", final_prompt)
                    self.assertIn("$.answer", final_prompt)

    async def test_second_invalid_schema_after_limit_stops_with_diagnostic(self):
        sent = []
        replies = [response_body("chat_completions", limit=True),
                   response_body("chat_completions", text="{}"), response_body("chat_completions", text="{}")]
        async with Provider(self.settings("chat_completions"), transport=self.transport(replies, sent)) as provider:
            with self.assertRaises(ProviderError) as error:
                await provider.generate(Result, "system", "user")
        self.assertEqual(3, len(sent))
        self.assertIn("两次输出均未通过结构校验", str(error.exception))

    async def test_permanent_http_errors_stop_without_additional_requests(self):
        for code in (400, 401, 403, 404, 422):
            with self.subTest(code=code):
                sent = []
                async with Provider(self.settings("chat_completions"), transport=self.transport(
                        [httpx.Response(code, json={"error": "private"})], sent)) as provider:
                    with self.assertRaises(ProviderError) as error:
                        await provider.generate(Result, "system", "user")
                self.assertEqual(1, len(sent))
                self.assertNotIn("private", str(error.exception))
        sent = []
        replies = [response_body("chat_completions", limit=True),
                   httpx.Response(400, json={"error": "private maximum"})]
        async with Provider(self.settings("chat_completions"), transport=self.transport(replies, sent)) as provider:
            with self.assertRaises(ProviderError) as error:
                await provider.generate(Result, "system", "user")
        self.assertEqual(2, len(sent))
        self.assertIn("24000", str(error.exception))
        self.assertIn("模型支持的输出长度", str(error.exception))
        self.assertNotIn("private", str(error.exception))


if __name__ == "__main__":
    unittest.main()
