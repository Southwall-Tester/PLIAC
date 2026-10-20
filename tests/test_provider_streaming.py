"""Observed model streams: real counters, bounded parsing and task attribution."""
import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learnmargin.models import APIConfig
from learnmargin.provider import Provider, ProviderError
from test_provider_truncation import response_body


class Result(BaseModel):
    answer: str


class Chunks(httpx.AsyncByteStream):
    def __init__(self, data, width=1, gate=None):
        self.data, self.width, self.gate = data, width, gate
        self.closed = False
        self.reads = 0

    async def __aiter__(self):
        for offset in range(0, len(self.data), self.width):
            self.reads += 1
            yield self.data[offset:offset + self.width]
            await asyncio.sleep(0)
        if self.gate:
            await self.gate.wait()

    async def aclose(self):
        self.closed = True


def frame(value, newline="\r\n"):
    data = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return ("data: " + data + newline + newline).encode("utf-8")


def chat_stream(text='{"answer":"完成"}', *, finish="stop", reasoning="private-thought", done=True):
    values = [frame({"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})]
    if reasoning:
        values.append(frame({"choices": [{"index": 0, "delta": {"reasoning_content": reasoning}}]}))
    for piece in (text[:5], text[5:]):
        values.append(frame({"choices": [{"index": 0, "delta": {"content": piece}}]}))
    if finish:
        values.append(frame({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}))
    values.append(frame({"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 9,
                                                 "secret_count": 99, "secret_text": "private-secret"}}))
    if done:
        values.append(frame("[DONE]"))
    return b": keepalive\r\n\r\n" + b"".join(values)


def responses_stream(text='{"answer":"完成"}', *, status="completed", terminal=True):
    result = response_body("responses", text=text, limit=status == "incomplete")
    result["status"] = status
    values = [frame({"type": "response.created", "response": {"status": "in_progress"}}),
              frame({"type": "response.reasoning_summary_text.delta", "delta": "private-summary"}),
              frame({"type": "response.reasoning_text.delta", "delta": "private-thought"}),
              frame({"type": "response.output_text.delta", "delta": text[:5]}),
              frame({"type": "response.output_text.delta", "delta": text[5:]})]
    if terminal:
        values.append(frame({"type": f"response.{status}", "response": result}))
    return b"".join(values)


def stream_response(body, *, width=1, gate=None, headers=None):
    stream = Chunks(body, width, gate)
    return httpx.Response(200, headers={"content-type": "text/event-stream; charset=utf-8",
                                       **(headers or {})}, stream=stream), stream


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, responses, events, sent, protocol="chat_completions", observer=True):
        def handle(request):
            sent.append(json.loads(request.content))
            return responses[len(sent) - 1]
        config = APIConfig(protocol=protocol, base_url="https://gateway.example/v1", model="synthetic")
        return Provider(config, transport=httpx.MockTransport(handle),
                        observer=events.append if observer else None)

    async def test_unobserved_calls_keep_non_streaming_payload(self):
        sent, events = [], []
        async with self.provider([httpx.Response(200, json=response_body("chat_completions"))],
                                 events, sent, observer=False) as provider:
            self.assertEqual((await provider.generate(Result, "system", "user")).answer, "complete")
        self.assertNotIn("stream", sent[0])
        self.assertNotIn("stream_options", sent[0])
        self.assertEqual(events, [])

    async def test_chat_arbitrary_utf8_and_crlf_chunks_only_emit_counters(self):
        for width in (1, 7, 4096):
            with self.subTest(width=width):
                events, sent = [], []
                response, stream = stream_response(chat_stream(), width=width)
                async with self.provider([response], events, sent) as provider:
                    with provider.observe_task("section:2:draft"):
                        result = await provider.generate(Result, "private-system", "private-material")
                    usage = provider.usage
                self.assertEqual(result.answer, "完成")
                self.assertTrue(stream.closed)
                self.assertTrue(sent[0]["stream"])
                self.assertEqual(sent[0]["stream_options"], {"include_usage": True})
                self.assertEqual(events[0]["phase"], "request_started")
                self.assertEqual(events[-2]["phase"], "validating")
                self.assertEqual(events[-1]["phase"], "completed")
                self.assertEqual(events[-1]["response_chars"], len('{"answer":"完成"}'))
                self.assertEqual(events[-1]["reasoning_chars"], len("private-thought"))
                self.assertEqual({e["task_id"] for e in events}, {"section:2:draft"})
                self.assertEqual(len({e["request_id"] for e in events}), 1)
                self.assertEqual(usage[0]["completion_tokens"], 9)
                self.assertNotIn("private", json.dumps(events) + json.dumps(usage))
                self.assertNotIn("完成", json.dumps(events, ensure_ascii=False))
                self.assertNotIn("secret_count", usage[0])

    async def test_responses_use_terminal_snapshot_without_double_counting(self):
        events, sent = [], []
        response, _ = stream_response(responses_stream(), width=3)
        async with self.provider([response], events, sent, "responses") as provider:
            result = await provider.generate(Result, "system", "user")
            usage = provider.usage
        self.assertEqual(result.answer, "完成")
        self.assertEqual(events[-1]["response_chars"], len('{"answer":"完成"}'))
        self.assertEqual(events[-1]["reasoning_chars"], len("private-summaryprivate-thought"))
        self.assertEqual(usage[0]["status"], "completed")
        self.assertNotIn("stream_options", sent[0])
        self.assertNotIn("private", json.dumps(events))

    async def test_concurrent_calls_keep_task_and_request_identity(self):
        events, sent = [], []
        one, _ = stream_response(chat_stream('{"answer":"one"}'), width=3)
        two, _ = stream_response(chat_stream('{"answer":"two-longer"}'), width=11)
        async with self.provider([one, two], events, sent) as provider:
            async def generate(task):
                with provider.observe_task(task):
                    return await provider.generate(Result, "system", task)
            result = await asyncio.gather(generate("section:1:draft"), generate("section:2:draft"))
        self.assertEqual([item.answer for item in result], ["one", "two-longer"])
        by_task = {task: [event for event in events if event["task_id"] == task]
                   for task in ("section:1:draft", "section:2:draft")}
        self.assertEqual(len({event["request_id"] for event in events}), 2)
        for task, expected in zip(by_task, ('{"answer":"one"}', '{"answer":"two-longer"}')):
            self.assertEqual(len({e["request_id"] for e in by_task[task]}), 1)
            self.assertEqual(by_task[task][-1]["response_chars"], len(expected))
            self.assertEqual(by_task[task][-1]["phase"], "completed")

    async def test_explicit_unsupported_stream_falls_back_once_and_marks_waiting(self):
        for code in (400, 422):
            events, sent = [], []
            responses = [httpx.Response(code, json={"error": {"param": "stream", "message": "not supported"}}),
                         httpx.Response(200, json=response_body("chat_completions"))]
            async with self.provider(responses, events, sent) as provider:
                self.assertEqual((await provider.generate(Result, "system", "user")).answer, "complete")
            self.assertEqual(len(sent), 2)
            self.assertTrue(sent[0]["stream"])
            self.assertNotIn("stream", sent[1])
            self.assertNotIn("stream_options", sent[1])
            self.assertEqual([e["attempt"] for e in events if e["phase"] == "request_started"], [1, 2])
            self.assertEqual([e["retry_reason"] for e in events if e["phase"] == "retry"], ["stream_unsupported"])
            self.assertTrue(any(e["transport"] == "json" and e["waiting"] for e in events))

    async def test_bad_request_unrelated_to_stream_is_not_replayed(self):
        events, sent = [], []
        response = httpx.Response(400, json={"error": {"param": "model", "message": "private model invalid"}})
        async with self.provider([response], events, sent) as provider:
            with self.assertRaises(ProviderError):
                await provider.generate(Result, "system", "user")
        self.assertEqual(len(sent), 1)
        self.assertEqual(events[-1]["phase"], "failed")
        self.assertNotIn("private", json.dumps(events))

    async def test_server_ignoring_stream_returns_json_without_duplicate_call(self):
        events, sent = [], []
        response = httpx.Response(200, json=response_body("chat_completions"))
        async with self.provider([response], events, sent) as provider:
            self.assertEqual((await provider.generate(Result, "system", "user")).answer, "complete")
        self.assertEqual(len(sent), 1)
        self.assertEqual(events[-1]["transport"], "json")
        self.assertEqual(events[-1]["response_chars"], len('{"answer":"complete"}'))

    async def test_transient_retry_keeps_same_logical_request(self):
        events, sent = [], []
        final, _ = stream_response(chat_stream(), width=4096)
        with patch("learnmargin.provider.asyncio.sleep", new_callable=AsyncMock):
            async with self.provider([httpx.Response(503), httpx.Response(429), final], events, sent) as provider:
                await provider.generate(Result, "system", "user")
        self.assertEqual(len(sent), 3)
        self.assertEqual(len({e["request_id"] for e in events}), 1)
        self.assertEqual([e["attempt"] for e in events if e["phase"] == "request_started"], [1, 2, 3])
        self.assertEqual([e["retry_reason"] for e in events if e["phase"] == "retry"], ["transient", "transient"])

    async def test_output_limit_and_schema_repair_preserve_existing_budgets(self):
        for protocol in ("chat_completions", "responses"):
            events, sent = [], []
            if protocol == "responses":
                bodies = [responses_stream(status="incomplete"), responses_stream("{}"), responses_stream()]
            else:
                bodies = [chat_stream(finish="length"), chat_stream("{}"), chat_stream()]
            responses = [stream_response(body, width=4096)[0] for body in bodies]
            async with self.provider(responses, events, sent, protocol) as provider:
                await provider.generate(Result, "system", "user")
                self.assertEqual(len(provider.usage), 3)
            key = "max_output_tokens" if protocol == "responses" else "max_tokens"
            self.assertEqual([p[key] for p in sent], [12000, 24000, 24000])
            self.assertEqual([e["retry_reason"] for e in events if e["phase"] == "retry"],
                             ["output_limit", "validation"])
            self.assertEqual(len([e for e in events if e["phase"] == "completed"]), 1)
            self.assertEqual(len({e["request_id"] for e in events}), 1)

    async def test_incomplete_stream_and_error_event_fail_without_replay(self):
        cases = [("chat_completions", chat_stream(finish=None, done=False)),
                 ("responses", responses_stream(terminal=False)),
                 ("responses", frame({"type": "error", "message": "private response error"})),
                 ("chat_completions", frame({"error": {"message": "private response error"}})),
                 ("responses", frame({"type": []})),
                 ("responses", frame({"type": "response.completed", "response": {"status": "in_progress"}})),
                 ("chat_completions", frame({"choices": [{"delta": {}, "finish_reason": []}]}))]
        for protocol, body in cases:
            events, sent = [], []
            response, stream = stream_response(body, width=4096)
            async with self.provider([response], events, sent, protocol) as provider:
                with self.assertRaises(ProviderError):
                    await provider.generate(Result, "system", "user")
            self.assertTrue(stream.closed)
            self.assertEqual(len(sent), 1)
            self.assertEqual(events[-1]["phase"], "failed")
            self.assertNotIn("private", json.dumps(events))

    async def test_cancel_releases_stream_and_emits_cancelled_not_completed(self):
        events, sent, received = [], [], asyncio.Event()
        partial = frame({"choices": [{"delta": {"content": '{"answer":"'}}]})
        response, stream = stream_response(partial, width=4096, gate=asyncio.Event())
        async with self.provider([response], events, sent) as provider:
            def observe(event):
                events.append(event)
                if event["phase"] == "receiving":
                    received.set()
            provider.observer = observe
            task = asyncio.create_task(provider.generate(Result, "system", "user"))
            await asyncio.wait_for(received.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(provider.usage, [])
        self.assertTrue(stream.closed)
        self.assertEqual(events[-1]["phase"], "cancelled")
        self.assertEqual(len(sent), 1)
        self.assertFalse(any(e["phase"] in ("completed", "failed") for e in events))

    async def test_total_deadline_still_bounds_a_live_stream(self):
        events, sent = [], []
        response, stream = stream_response(frame({"choices": [{"delta": {"content": "{"}}]}),
                                           width=4096, gate=asyncio.Event())
        async with self.provider([response], events, sent) as provider:
            provider.config = provider.config.model_copy(update={"timeout_seconds": .03})
            with self.assertRaises(ProviderError) as error:
                await provider.generate(Result, "system", "user")
        self.assertIn("超时", str(error.exception))
        self.assertTrue(stream.closed)
        self.assertEqual(events[-1]["phase"], "failed")
        self.assertEqual(len(sent), 1)

    async def test_observer_failure_cannot_fail_or_repeat_a_completed_call(self):
        events, sent = [], []
        response, _ = stream_response(chat_stream(), width=4096)
        async with self.provider([response], events, sent) as provider:
            def broken(event):
                raise RuntimeError("progress storage unavailable")
            provider.observer = broken
            self.assertEqual((await provider.generate(Result, "system", "user")).answer, "完成")
        self.assertEqual(len(sent), 1)

    async def test_stream_respects_compression_size_utf8_and_json_depth_guards(self):
        cases = [
            (b"not a compressed payload", {"content-encoding": "gzip"}, None),
            (b"x" * 100, {}, 32),
            (b"data: \xff\n\n", {}, None),
            (frame("[" * 129 + "]" * 129), {}, None),
        ]
        for body, headers, bound in cases:
            events, sent = [], []
            response, stream = stream_response(body, width=8, headers=headers)
            async with self.provider([response], events, sent) as provider:
                with patch("learnmargin.provider.MAX_RESPONSE_BYTES", bound or 8 * 1024 * 1024):
                    with self.assertRaises(ProviderError):
                        await provider.generate(Result, "system", "user")
            self.assertTrue(stream.closed)
            self.assertEqual(len(sent), 1)
            self.assertEqual(events[-1]["phase"], "failed")
            if headers:
                self.assertEqual(stream.reads, 0)

    async def test_multiline_data_and_bare_cr_endings_remain_valid_sse(self):
        events, sent = [], []
        text = '{"answer":"complete"}'
        first = json.dumps({"choices": [{"delta": {"content": text}}]})
        body = (b"event: message\rdata: {\rdata: " + first[1:].encode("utf-8") + b"\r\r" +
                frame({"choices": [{"delta": {}, "finish_reason": "stop"}]}, newline="\r") +
                b"data: [DONE]\r")
        response, _ = stream_response(body, width=1)
        async with self.provider([response], events, sent) as provider:
            self.assertEqual((await provider.generate(Result, "system", "user")).answer, "complete")
        self.assertEqual(events[-1]["response_chars"], len(text))


if __name__ == "__main__":
    unittest.main()
