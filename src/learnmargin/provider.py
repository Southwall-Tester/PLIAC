"""Two configurable API protocols with bounded retries and validated JSON output."""
from __future__ import annotations

import asyncio
import base64
import codecs
from contextlib import contextmanager
from contextvars import ContextVar
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Callable, TypeVar
from urllib.parse import urlsplit
import uuid

import httpx
from pydantic import BaseModel, ValidationError

from .config import validate_api_config
from .models import APIConfig, ConnectionTestResult
from .reasoning import reasoning_parameters, reasoning_profile

T = TypeVar("T", bound=BaseModel)
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 22 * 1024 * 1024
DEFAULT_OUTPUT_TOKENS = 12000
MAX_OUTPUT_TOKENS = 24000
USAGE_FIELDS = frozenset({
    "input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens",
    "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
})


class ProviderError(ValueError):
    pass


class OutputLimitError(ProviderError):
    """Only an explicit upstream output-token limit permits a larger retry."""


class JSONDepthError(ValueError):
    pass


def bounded_json_loads(text: str) -> object:
    """Bound nesting before the parser allocates a deeply recursive structure."""
    depth = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > 128:
                raise JSONDepthError("JSON 嵌套层级过深。")
        elif char in "]}":
            depth -= 1
    return json.loads(text)


def decode_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    value = bounded_json_loads(text)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def output_error_summary(error: ValueError | RecursionError, schema: type[BaseModel]) -> str:
    """Describe output faults without echoing model values or arbitrary field names."""
    if isinstance(error, json.JSONDecodeError):
        category = "invalid_escape" if error.msg.startswith("Invalid \\escape") else "invalid_json"
        return f"JSON 语法错误（{category}），第 {error.lineno} 行、第 {error.colno} 列"
    if isinstance(error, (RecursionError, JSONDepthError)):
        return "JSON 嵌套层级过深（too_deep）"
    if not isinstance(error, ValidationError):
        return "JSON 顶层必须是对象（object_required）"

    fields: set[str] = set()

    def collect_fields(node):
        if isinstance(node, dict):
            fields.update(node.get("properties", {}))
            for value in node.values():
                collect_fields(value)
        elif isinstance(node, list):
            for value in node:
                collect_fields(value)

    collect_fields(schema.model_json_schema())
    error_types = {
        "missing": "缺少必填字段",
        "extra_forbidden": "存在未定义字段",
        "string_type": "应为字符串",
        "string_too_short": "字符串长度不足",
        "string_too_long": "字符串超出长度限制",
        "list_type": "应为数组",
        "dict_type": "应为对象",
        "model_type": "应为对象",
        "int_type": "应为整数",
        "int_parsing": "应为整数",
        "literal_error": "取值不在允许范围内",
        "too_short": "项目数量不足",
        "too_long": "项目数量超出限制",
        "greater_than_equal": "数值小于允许下限",
        "less_than_equal": "数值大于允许上限",
        "value_error": "未满足字段约束或字段间条件",
        "question_answer_required": "需要作答的侧栏提示必须填写非空参考答案 answer",
        "action_answer_not_allowed": "流程指导 action 的 answer 必须为 null；新增知识问题使用 question 并提供答案",
        "answer_options_invalid": "知识题须有3至4个不同的具体答案选项，唯一编号A至D，并用answer_key指定正确选项；流程指导不设选项",
        "guidance_placement_without_practice": "没有 practice 时，侧栏 placement 不能选 before_practice 或 after_practice",
    }
    summaries = []
    for detail in error.errors(include_url=False, include_input=False, include_context=False)[:6]:
        location = "$"
        for part in detail["loc"][:8]:
            if isinstance(part, int):
                location += f"[{part}]"
            elif part in fields:
                location += f".{part}"
            else:
                location += ".[未定义字段]"
        kind = detail["type"] if detail["type"] in error_types else "value_error"
        summaries.append(f"{location}：{error_types[kind]}（{kind}）")
    return "；".join(summaries)


class Provider:
    def __init__(self, config: APIConfig, *, transport: httpx.AsyncBaseTransport | None = None,
                 observer: Callable[[dict], None] | None = None):
        self.config = validate_api_config(config)
        key = self.config.api_key.get_secret_value()
        try:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout_seconds, connect=20),
                # Keep explicitly configured HTTPS proxies usable, but never send
                # local plaintext traffic through a proxy inherited from the shell.
                follow_redirects=False, trust_env=urlsplit(self.config.base_url).scheme == "https",
                transport=transport,
                # Request uncompressed bodies so hostile payloads cannot expand
                # without a bound inside HTTPX's automatic content decoder.
                headers={"Accept-Encoding": "identity", **({"Authorization": f"Bearer {key}"} if key else {})},
            )
        except (ValueError, OSError, httpx.HTTPError, httpx.InvalidURL):
            # HTTPX may echo a malformed environment proxy URL (whose username
            # itself can be a credential), or a private certificate path.
            raise ProviderError("无法初始化 API 连接，请检查代理与证书配置。") from None
        self.usage: list[dict] = []
        self.observer = observer
        self._observation = ContextVar("provider_observation", default=None)
        self._task_id = ContextVar("provider_task_id", default=None)
        self._stream_unsupported = False

    @contextmanager
    def observe_task(self, task_id: str):
        """Bind a pipeline-owned identifier in this async task, not on the instance."""
        token = self._task_id.set(task_id)
        try:
            yield
        finally:
            self._task_id.reset(token)

    def _emit(self, phase: str, **extra):
        state = self._observation.get()
        if state is None:
            return
        event = {name: state[name] for name in (
            "request_id", "schema", "task_id", "attempt", "response_chars",
            "reasoning_chars", "transport", "waiting")}
        event.update(phase=phase, **extra)
        try:
            state["observer"](event)
        except Exception:
            # Progress persistence must not abort or duplicate a model request.
            pass

    def _received(self, content="", reasoning=""):
        state = self._observation.get()
        if state is not None:
            state["response_chars"] += len(content) if isinstance(content, str) else 0
            state["reasoning_chars"] += len(reasoning) if isinstance(reasoning, str) else 0
            state["waiting"] = False
            self._emit("receiving")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.client.aclose()

    async def _request(self, payload: dict, *, retry_transient: bool = True,
                       timeout_seconds: float | None = None) -> dict:
        limit = self.config.timeout_seconds if timeout_seconds is None else timeout_seconds
        try:
            # I/O timeouts alone can be kept alive by a byte-at-a-time response.
            # This deadline also covers retries, their delays, and body reading.
            async with asyncio.timeout(limit):
                return await self._request_with_retries(payload, retry_transient, limit)
        except (TimeoutError, httpx.TimeoutException):
            if timeout_seconds is not None:
                raise ProviderError("连接测试超时，请检查服务状态和网络连接后重试。") from None
            raise ProviderError(
                f"模型响应超时（单次请求限时 {limit:g} 秒，包含服务重试与响应读取）。"
                "请缩小学习范围，或请维护者提高模型请求超时后重试。"
            ) from None
        except httpx.HTTPError:
            raise ProviderError("无法连接 API，请检查服务地址和网络连接。") from None

    async def _request_with_retries(self, payload: dict, retry_transient: bool, timeout_seconds: float) -> dict:
        endpoint = "/responses" if self.config.protocol == "responses" else "/chat/completions"
        attempts = 3 if retry_transient else 1
        transient_attempt = 0
        while transient_attempt < attempts:
            state = self._observation.get()
            streaming = state is not None and not self._stream_unsupported
            sent = dict(payload)
            if streaming:
                sent["stream"] = True
                if self.config.protocol == "chat_completions":
                    sent["stream_options"] = {"include_usage": True}
            if state is not None:
                state.update(attempt=state["attempt"] + 1, response_chars=0, reasoning_chars=0,
                             transport="sse" if streaming else "json", waiting=True)
                self._emit("request_started")
            fallback = False
            async with self.client.stream(
                "POST", self.config.base_url.rstrip("/") + endpoint, json=sent,
                timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 20)),
            ) as response:
                retry = response.status_code in {429, 502, 503, 504} and transient_attempt < attempts - 1
                if streaming and response.status_code in {400, 422}:
                    body = await self._read_body(response)
                    fallback = self._unsupported_stream(body)
                if fallback:
                    self._stream_unsupported = True
                    self._emit("retry", retry_reason="stream_unsupported")
                elif not retry:
                    if response.status_code in {401, 403}:
                        raise ProviderError("API 鉴权失败，请核对该服务的密钥与模型权限。")
                    if response.status_code in {402, 429}:
                        raise ProviderError("API 请求额度或速率受限，请检查账户额度后稍后重试。")
                    if response.status_code in {400, 404, 405, 422}:
                        limit = payload.get("max_output_tokens", payload.get("max_completion_tokens", payload.get("max_tokens")))
                        budget_note = (f"本次请求的输出上限为 {limit} token，请核对模型支持的输出长度。"
                                       if type(limit) is int and limit > DEFAULT_OUTPUT_TOKENS else "")
                        raise ProviderError(
                            f"API 返回 HTTP {response.status_code}。{budget_note}请核对服务地址、协议、模型名与 JSON 模式。"
                        )
                    if response.status_code >= 300:
                        raise ProviderError(
                            f"API 返回 HTTP {response.status_code}。请核对协议、模型名、视觉能力与 JSON 模式。"
                        )
                    if streaming and response.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "text/event-stream":
                        result = await self._read_sse(response)
                    else:
                        if state is not None:
                            state.update(transport="json", waiting=True)
                            self._emit("receiving")
                        body = await self._read_body(response)
                        try:
                            result = bounded_json_loads(body.decode("utf-8-sig"))
                        except (ValueError, RecursionError):
                            raise ProviderError("API 未返回有效 JSON 响应，请检查 Base URL。") from None
                        if not isinstance(result, dict):
                            raise ProviderError("API 响应结构不受支持。")
                        self._count_buffered(result)
            if fallback:
                continue
            if retry:
                self._emit("retry", retry_reason="transient")
                await asyncio.sleep(2 ** (transient_attempt + 1))
                transient_attempt += 1
                continue
            self._record_usage(result, payload)
            return result
        raise ProviderError("API 暂时不可用。")

    @staticmethod
    def _unsupported_stream(body):
        try:
            value = bounded_json_loads(body.decode("utf-8-sig"))
        except (ValueError, RecursionError):
            return False
        error = value.get("error") if isinstance(value, dict) else None
        if not isinstance(error, dict):
            return False
        param = error.get("param")
        message = str(error.get("message", "")).lower()
        return (param in ("stream", "stream_options", "stream_options.include_usage")
                or ("stream" in message and any(word in message for word in
                    ("unsupported", "not supported", "does not support", "unknown parameter", "unrecognized", "not allowed", "不支持"))))

    def _count_buffered(self, result):
        state = self._observation.get()
        if state is None:
            return
        content, reasoning = [], []
        if self.config.protocol == "responses":
            for item in result.get("output", []) if isinstance(result.get("output"), list) else []:
                if not isinstance(item, dict):
                    continue
                for part in item.get("content", []) if isinstance(item.get("content"), list) else []:
                    if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                        content.append(part["text"])
                for part in item.get("summary", []) if isinstance(item.get("summary"), list) else []:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        reasoning.append(part["text"])
        else:
            choices = result.get("choices")
            choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
            message = choice.get("message")
            if isinstance(message, dict):
                if isinstance(message.get("content"), str):
                    content.append(message["content"])
                if isinstance(message.get("reasoning_content"), str):
                    reasoning.append(message["reasoning_content"])
        state["response_chars"] = max(state["response_chars"], sum(map(len, content)))
        state["reasoning_chars"] = max(state["reasoning_chars"], sum(map(len, reasoning)))
        state["waiting"] = False
        self._emit("receiving")

    def _record_usage(self, result, payload):
        usage = result.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        # Only documented counters are persisted; arbitrary upstream keys can
        # contain secrets even when their values are harmless numbers.
        record = {key: value for key, value in usage.items()
                  if key in USAGE_FIELDS and type(value) in {int, float}
                  and 0 <= value <= 2**63 - 1 and math.isfinite(value)}
        # Persist only known enum values and numeric budgets, never arbitrary
        # upstream messages, refusal text or private reasoning content.
        choices = result.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        finish_reason = choice.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason in {"stop", "length", "content_filter", "tool_calls", "function_call"}:
            record["finish_reason"] = finish_reason
        status = result.get("status")
        if isinstance(status, str) and status in {"completed", "incomplete", "failed", "cancelled"}:
            record["status"] = status
        incomplete = result.get("incomplete_details")
        reason = incomplete.get("reason") if isinstance(incomplete, dict) else None
        if isinstance(reason, str) and reason in {"max_output_tokens", "content_filter"}:
            record["incomplete_reason"] = reason
        limit = payload.get("max_output_tokens", payload.get("max_completion_tokens", payload.get("max_tokens")))
        if type(limit) is int and 0 < limit <= MAX_OUTPUT_TOKENS:
            record["requested_output_tokens"] = limit
        for key in ("output_tokens_details", "completion_tokens_details"):
            details = usage.get(key)
            count = details.get("reasoning_tokens") if isinstance(details, dict) else None
            if type(count) is int and 0 <= count <= 2**63 - 1:
                record["reasoning_tokens"] = count
        self.usage.append(record)

    @staticmethod
    def _check_response_headers(response: httpx.Response):
        if response.headers.get("content-encoding", "identity").strip().lower() not in {"", "identity"}:
            raise ProviderError("API 返回了未请求的压缩响应，请配置网关返回未压缩 JSON。")
        length = response.headers.get("content-length")
        if length is not None:
            try:
                announced = int(length)
            except ValueError:
                raise ProviderError("API 返回了无效的响应长度。") from None
            if announced < 0 or announced > MAX_RESPONSE_BYTES:
                raise ProviderError("API 响应过大，请缩小学习范围或检查服务配置。")

    @staticmethod
    async def _read_body(response: httpx.Response) -> bytes:
        Provider._check_response_headers(response)
        if response.is_stream_consumed:
            # Already-buffered responses are used by embedded/mock transports.
            data = response.content
            if len(data) > MAX_RESPONSE_BYTES:
                raise ProviderError("API 响应过大，请缩小学习范围或检查服务配置。")
            return data
        data = bytearray()
        async for chunk in response.aiter_raw(chunk_size=65536):
            if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                raise ProviderError("API 响应过大，请缩小学习范围或检查服务配置。")
            data.extend(chunk)
        return bytes(data)

    @staticmethod
    async def _sse_events(response: httpx.Response):
        """Decode bounded UTF-8 SSE across arbitrary byte and CR/LF boundaries."""
        Provider._check_response_headers(response)
        decoder = codecs.getincrementaldecoder("utf-8-sig")()
        buffer, data, event_name, size = "", [], "", 0

        async def chunks():
            if response.is_stream_consumed:
                yield response.content
            else:
                async for chunk in response.aiter_raw():
                    yield chunk

        async for chunk in chunks():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ProviderError("API 响应过大，请缩小学习范围或检查服务配置。")
            try:
                buffer += decoder.decode(chunk)
            except UnicodeError:
                raise ProviderError("API 流式响应不是有效 UTF-8 文本。") from None
            while True:
                boundaries = [i for i in (buffer.find("\r"), buffer.find("\n")) if i >= 0]
                if not boundaries:
                    break
                index = min(boundaries)
                if buffer[index] == "\r" and index == len(buffer) - 1:
                    break
                line = buffer[:index]
                width = 2 if buffer[index:index + 2] == "\r\n" else 1
                buffer = buffer[index + width:]
                if not line:
                    if data:
                        yield event_name, "\n".join(data)
                    data, event_name = [], ""
                elif line.startswith("data:"):
                    value = line[5:]
                    data.append(value[1:] if value.startswith(" ") else value)
                elif line.startswith("event:"):
                    event_name = line[6:].strip()
        try:
            buffer += decoder.decode(b"", final=True)
        except UnicodeError:
            raise ProviderError("API 流式响应不是有效 UTF-8 文本。") from None
        # Dispatch a complete final data line even if the proxy omitted its
        # final blank line; completion is still verified by protocol below.
        for line in buffer.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if line.startswith("data:"):
                value = line[5:]
                data.append(value[1:] if value.startswith(" ") else value)
        if data:
            yield event_name, "\n".join(data)

    async def _read_sse(self, response: httpx.Response) -> dict:
        pieces, usage, finish_reason, refusal = [], {}, None, False
        async for event_name, raw in self._sse_events(response):
            if raw.strip() == "[DONE]":
                if self.config.protocol == "chat_completions" and finish_reason is not None:
                    return {"choices": [{"message": {"content": "".join(pieces), "refusal": refusal},
                                         "finish_reason": finish_reason}], "usage": usage}
                break
            try:
                event = bounded_json_loads(raw)
            except (ValueError, RecursionError):
                raise ProviderError("API 流式响应包含无效 JSON 事件。") from None
            if not isinstance(event, dict):
                raise ProviderError("API 流式响应事件结构不受支持。")
            if event.get("error") or event.get("type", event_name) == "error":
                raise ProviderError("模型服务在流式生成中返回错误，请稍后重试。")
            if self.config.protocol == "responses":
                kind = event.get("type", event_name)
                if not isinstance(kind, str):
                    raise ProviderError("API 流式响应的事件类型不受支持。")
                if kind in {"response.output_text.delta", "response.reasoning_text.delta",
                            "response.reasoning_summary_text.delta"}:
                    delta = event.get("delta")
                    if not isinstance(delta, str):
                        raise ProviderError("API 流式响应没有有效的文本增量。")
                    if kind == "response.output_text.delta":
                        self._received(content=delta)
                    else:
                        self._received(reasoning=delta)
                elif kind in {"response.completed", "response.incomplete", "response.failed", "response.cancelled"}:
                    result = event.get("response")
                    if not isinstance(result, dict):
                        raise ProviderError("API 流式响应没有有效的完成记录。")
                    expected_status = kind.split(".", 1)[1]
                    if result.get("status", expected_status) != expected_status:
                        raise ProviderError("API 流式响应的完成状态不一致。")
                    result.setdefault("status", expected_status)
                    self._count_buffered(result)
                    return result
            else:
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                choices = event.get("choices")
                if not isinstance(choices, list):
                    raise ProviderError("API 流式响应的 choices 结构不受支持。")
                if not choices:
                    continue
                choice = choices[0]
                if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                    raise ProviderError("API 流式响应的选项结构不受支持。")
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    raise ProviderError("API 流式响应的 delta 结构不受支持。")
                content, reasoning = delta.get("content"), delta.get("reasoning_content")
                if content is not None and not isinstance(content, str):
                    raise ProviderError("API 流式响应没有有效的文本增量。")
                if reasoning is not None and not isinstance(reasoning, str):
                    raise ProviderError("API 流式响应没有有效的推理增量。")
                if isinstance(content, str):
                    pieces.append(content)
                refusal = refusal or bool(delta.get("refusal"))
                if content or reasoning:
                    self._received(content=content, reasoning=reasoning)
                if choice.get("finish_reason") is not None:
                    if not isinstance(choice["finish_reason"], str):
                        raise ProviderError("API 流式响应的完成原因不受支持。")
                    finish_reason = choice["finish_reason"]
        if self.config.protocol == "chat_completions" and finish_reason is not None:
            return {"choices": [{"message": {"content": "".join(pieces), "refusal": refusal},
                                 "finish_reason": finish_reason}], "usage": usage}
        raise ProviderError("模型流式响应在完成前中断，请重新尝试。")

    async def test_connection(self) -> ConnectionTestResult:
        """Send one bounded text-only probe; never retry or include learning material."""
        instruction = ('Return only this JSON object: {"ok":true}.' if self.config.json_mode
                       else "Reply only OK.")
        payload = self._payload("You are testing an API connection.", instruction, [])
        limit_key = ("max_output_tokens" if self.config.protocol == "responses" else
                     "max_completion_tokens" if "max_completion_tokens" in payload else "max_tokens")
        payload[limit_key] = 256
        timeout_seconds = min(self.config.timeout_seconds, 30)
        started = perf_counter()
        result = await self._request(payload, retry_transient=False, timeout_seconds=timeout_seconds)
        if result.get("error") or not self._text(result).strip():
            raise ProviderError("API 未返回有效文本，连接测试未通过。请核对服务协议和模型名。")
        return ConnectionTestResult(model=self.config.model, latency_ms=round((perf_counter() - started) * 1000))

    def _payload(self, system: str, user: str, images: list[Path]) -> dict:
        encoded = []
        total = 0
        for image in images:
            with image.open("rb") as stream:
                data = stream.read(MAX_IMAGE_BYTES - total + 1)
            total += len(data)
            if total > MAX_IMAGE_BYTES:
                raise ProviderError("本轮图片数据过大，请缩小范围后再生成。")
            mime = "image/jpeg" if image.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            encoded.append(f"data:{mime};base64," + base64.b64encode(data).decode("ascii"))
        if self.config.protocol == "responses":
            content = [{"type": "input_text", "text": user}]
            content.extend({"type": "input_image", "image_url": url} for url in encoded)
            result = {"model": self.config.model, "instructions": system,
                      "input": [{"role": "user", "content": content}], "max_output_tokens": DEFAULT_OUTPUT_TOKENS,
                      "store": False}
            if self.config.json_mode:
                result["text"] = {"format": {"type": "json_object"}}
        else:
            content = [{"type": "text", "text": user}]
            content.extend({"type": "image_url", "image_url": {"url": url}} for url in encoded)
            result = {"model": self.config.model, "messages": [{"role": "system", "content": system},
                      {"role": "user", "content": content if encoded else user}], "max_tokens": DEFAULT_OUTPUT_TOKENS}
            if self.config.json_mode:
                result["response_format"] = {"type": "json_object"}
        result.update(reasoning_parameters(self.config))
        if (self.config.protocol == "chat_completions"
                and self.config.base_url == "https://api.openai.com/v1"
                and reasoning_profile(self.config) is not None):
            result["max_completion_tokens"] = result.pop("max_tokens")
        return result

    def _text(self, response: dict) -> str:
        if self.config.protocol == "responses":
            if response.get("status") == "incomplete":
                details = response.get("incomplete_details")
                reason = details.get("reason") if isinstance(details, dict) else None
                if reason == "max_output_tokens":
                    raise OutputLimitError("模型输出达到本次请求的 token 上限。")
                if reason == "content_filter":
                    raise ProviderError("模型服务因内容过滤停止生成，请检查资料内容或联系模型服务方。")
                raise ProviderError("模型服务返回了未完成状态，请检查服务状态后重试。")
            if response.get("status") in {"failed", "cancelled"}:
                raise ProviderError("模型服务未完成本次请求，请检查服务状态后重试。")
            output = response.get("output")
            if not isinstance(output, list):
                raise ProviderError("API 响应的 output 结构不受支持。")
            pieces = []
            for item in output:
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    raise ProviderError("API 响应的 content 结构不受支持。")
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "refusal":
                        raise ProviderError("模型服务拒绝了本次生成请求，请检查资料内容或联系模型服务方。")
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        if not isinstance(part.get("text"), str):
                            raise ProviderError("API 响应没有有效的文本内容。")
                        pieces.append(part["text"])
            return "\n".join(pieces)
        choices = response.get("choices") or []
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderError("模型响应没有可用内容。")
        if choices[0].get("finish_reason") == "length":
            raise OutputLimitError("模型输出达到本次请求的 token 上限。")
        if choices[0].get("finish_reason") == "content_filter":
            raise ProviderError("模型服务因内容过滤停止生成，请检查资料内容或联系模型服务方。")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ProviderError("API 响应的 message 结构不受支持。")
        if message.get("refusal"):
            raise ProviderError("模型服务拒绝了本次生成请求，请检查资料内容或联系模型服务方。")
        content = message.get("content")
        return content if isinstance(content, str) else ""

    async def generate(self, schema: type[T], system: str, user: str,
                       images: list[Path] | None = None) -> T:
        observer = self.observer if callable(self.observer) else None
        state = ({"observer": observer, "request_id": uuid.uuid4().hex,
                  "schema": schema.__name__, "task_id": self._task_id.get(),
                  "attempt": 0, "response_chars": 0, "reasoning_chars": 0,
                  "transport": "sse", "waiting": True} if observer else None)
        token = self._observation.set(state)
        try:
            result = await self._generate(schema, system, user, images)
            self._emit("completed")
            return result
        except asyncio.CancelledError:
            self._emit("cancelled")
            raise
        except Exception:
            self._emit("failed")
            raise
        finally:
            self._observation.reset(token)

    async def _generate(self, schema: type[T], system: str, user: str,
                        images: list[Path] | None = None) -> T:
        schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        instructions = system + "\n只输出完整 JSON 对象，符合下面 JSON Schema；不要输出代码围栏：\n" + schema_text
        output_budget, repair_attempt = DEFAULT_OUTPUT_TOKENS, 0
        # At most one output-budget retry plus one existing schema-repair retry.
        # A truncated result is discarded; only a complete validated object wins.
        for _ in range(3):
            payload = self._payload(instructions, user, images or [])
            limit_key = ("max_output_tokens" if self.config.protocol == "responses" else
                         "max_completion_tokens" if "max_completion_tokens" in payload else "max_tokens")
            payload[limit_key] = output_budget
            result = await self._request(payload)
            try:
                text = self._text(result)
            except OutputLimitError:
                if output_budget == MAX_OUTPUT_TOKENS:
                    raise ProviderError(
                        f"已将模型输出上限从 {DEFAULT_OUTPUT_TOKENS} 扩大到 {MAX_OUTPUT_TOKENS} token 重试，"
                        "结果仍达到长度上限。请选择更小的学习单元，或使用支持更长输出的模型。"
                    ) from None
                output_budget = MAX_OUTPUT_TOKENS
                self._emit("retry", retry_reason="output_limit")
                continue
            try:
                self._emit("validating")
                return schema.model_validate(decode_json(text))
            except (ValueError, RecursionError) as error:
                summary = output_error_summary(error, schema)
                if repair_attempt:
                    raise ProviderError(
                        f"{schema.__name__} 两次输出均未通过结构校验（已重试 1 次）：{summary}。"
                    ) from None
                repair_attempt += 1
                self._emit("retry", retry_reason="validation")
                user += (
                    f"\n上次输出未通过结构校验，具体问题：{summary}。"
                    "\n请对照 JSON Schema 和上述生成要求修正这些位置，重新生成完整 JSON 对象，"
                    "保留所需全部字段与材料引用；不要只输出补丁或错误解释。"
                    "JSON 字符串中的换行、引号和 LaTeX 反斜杠必须正确转义。"
                )
        raise ProviderError("模型输出不可用。")
