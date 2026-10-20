"""Synthetic choice generation and cache contracts, with no live model calls."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learnmargin.models import APIConfig
from learnmargin.provider import ProviderError
from pliac.answer_options import get_generated
from pliac.choice_generation import ChoiceProvider, ChoiceReply, prepare_choice_requests

CONFIG = APIConfig(base_url="http://127.0.0.1:9999/v1", api_key="synthetic_secret", model="synthetic")


def request(scope="synthetic-question", answer="验证集用于比较候选模型。"):
    return dict(scope=scope, prompt="验证集的用途是什么？", reference_answer=answer,
                misconception="混淆验证与最终测试", context="训练、验证、测试分别承担不同职责。")


def reply(items):
    return ChoiceReply(items=[
        dict(item_id=item["item_id"], options=[
            dict(id="A", text=item["reference_answer"]),
            dict(id="B", text="用于拟合所有候选模型的参数。"),
            dict(id="C", text="用于只做一次的最终泛化评估。"),
        ], answer_key="A") for item in items])


class ChoiceGenerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.enterContext(patch.object(ChoiceProvider, "choices", side_effect=reply))

    async def test_cache_preserves_choices_and_skips_provider_configuration(self):
        source = request()
        first = await prepare_choice_requests([source], self.root, CONFIG)
        self.model.side_effect = AssertionError("Cached choices must not call the model.")
        second = await prepare_choice_requests([source], self.root)
        self.assertEqual(first, second)
        bundle = second[source["scope"]]
        self.assertEqual(bundle["prompt"], source["prompt"])
        self.assertEqual(next(o["text"] for o in bundle["options"] if o["id"] == bundle["answer_key"]),
                         source["reference_answer"])
        self.assertEqual(get_generated(source["scope"]), bundle)
        self.assertNotIn("synthetic_secret", next(self.root.glob("*.json")).read_text(encoding="utf-8"))

    async def test_changed_reference_invalidates_cache_without_overwriting_old_set(self):
        first = await prepare_choice_requests([request()], self.root, CONFIG)
        changed = request(answer="验证集仅用于选择超参数，不参与测试集的最终评分。")
        second = await prepare_choice_requests([changed], self.root, CONFIG)
        self.assertEqual(self.model.call_count, 2)
        self.assertNotEqual(first, second)
        self.assertEqual(len(list(self.root.glob("*.json"))), 2)

    async def test_simultaneous_requests_share_preparation(self):
        async def slow(items):
            await asyncio.sleep(.03)
            return reply(items)
        self.model.side_effect = slow
        a, b = await asyncio.gather(
            prepare_choice_requests([request()], self.root, CONFIG),
            prepare_choice_requests([request()], self.root, CONFIG))
        self.assertEqual(a, b)
        self.assertEqual(self.model.call_count, 1)

    async def test_large_request_is_batched_and_every_task_has_its_own_set(self):
        requests = [request(scope=f"question-{index}") for index in range(8)]
        result = await prepare_choice_requests(requests, self.root, CONFIG)
        self.assertEqual(self.model.call_count, 2)
        self.assertEqual(set(result), {r["scope"] for r in requests})
        self.assertEqual(len(list(self.root.glob("*.json"))), 8)

    async def test_missing_or_duplicate_model_items_do_not_populate_cache(self):
        bad = reply([{"item_id": "wrong-item", "reference_answer": "某个答案。"}])
        self.model.return_value = bad
        self.model.side_effect = None
        with self.assertRaises(ProviderError):
            await prepare_choice_requests([request()], self.root, CONFIG)
        self.assertFalse(list(self.root.glob("*.json")))

    async def test_unfounded_or_duplicate_inputs_are_rejected_before_model_call(self):
        for requests in ([dict(scope="empty", prompt="解释这个概念。")],
                         [request(), request()]):
            with self.subTest(requests=requests), self.assertRaises(ValueError):
                await prepare_choice_requests(requests, self.root, CONFIG)
        self.model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
