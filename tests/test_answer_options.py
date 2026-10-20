"""Task-related recognition choices and provenance, independent of any model."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent.course_graph import CourseGraphError
from pliac.answer_options import (
    build_choice_bundle, bundle_for_request, node_choice_request, public_bundle,
    register_generated, selected_response,
)


class AnswerOptionsTests(unittest.TestCase):
    def test_authored_options_override_generated_and_keep_their_identity(self):
        options = [{"id": "yes", "text": "退出状态为 1"}, {"id": "no", "text": "退出状态为 0"}]
        register_generated("authored-test", {"prompt": "不同题目", "options": [{"id": "A", "text": "不同答案"}],
                                            "answer_key": "A", "origin": "model_generated", "answer_mode": "recognition"})
        result = build_choice_bundle("grep 没有找到匹配行时退出状态是什么？", existing_options=options,
                                     answer_key="yes", scope="authored-test")
        self.assertEqual(result["options"], options)
        self.assertEqual(result["answer_key"], "yes")
        self.assertEqual(result["origin"], "authored")
        self.assertNotIn("answer_key", public_bundle(result))
        other_key = build_choice_bundle(result["prompt"], existing_options=options, answer_key="no", scope="authored-test")
        self.assertEqual(other_key["option_set_id"], result["option_set_id"])
        self.assertEqual(options, [{"id": "yes", "text": "退出状态为 1"}, {"id": "no", "text": "退出状态为 0"}])

    def test_reference_and_same_question_alternatives_keep_original_stem(self):
        examples = [
            ("终端与 Shell 分别负责什么？", "终端处理文字输入输出，Shell 解析并执行命令。",
             ["终端负责解析 Shell 语法，Shell 只显示字符。", "终端与 Shell 都是 Linux 内核。"]),
            ("grep 没有找到匹配行时退出状态是什么？", "退出状态为 1。",
             ["退出状态为 0。", "无论是否匹配都不返回退出状态。"]),
            ("for file in 'a one.txt' 'b.txt' 的循环体执行几次？", "执行两次，引号保护带空格的文件名。",
             ["执行三次，空格把第一个文件名拆成两项。", "只执行一次，整个列表是一个文件名。"]),
            ("公平骰子掷一次，出现偶数的概率是多少？", "三个偶数结果占六个等可能结果，概率为 1/2。",
             ["只有数字 2 是偶数，概率为 1/6。", "所有六个结果都是偶数，概率为 1。"]),
        ]
        for prompt, answer, alternatives in examples:
            with self.subTest(prompt=prompt):
                result = build_choice_bundle(prompt, answer, alternatives=alternatives, scope=prompt)
                self.assertEqual(result["prompt"], prompt)
                self.assertEqual({item["text"] for item in result["options"]}, {answer, *alternatives})
                self.assertEqual(next(item["text"] for item in result["options"]
                                      if item["id"] == result["answer_key"]), answer)
                self.assertEqual(result, build_choice_bundle(prompt, answer, alternatives=alternatives, scope=prompt))

    def test_no_reference_does_not_invent_a_scored_answer(self):
        result = build_choice_bundle("如何比较这两个尚未提供的方案？", scope="missing-reference")
        self.assertEqual(result["answer_mode"], "support_request")
        self.assertEqual(result["answer_key"], "")
        self.assertIn("哪种讲解", result["prompt"])

    def test_content_fingerprint_and_registered_generation_are_stable(self):
        graph = {"id": "probability", "version": 1}
        node = {"id": "coin", "title": "概率", "check_question": "公平硬币正面概率？",
                "expected_answer": "1/2", "misconception": "把可能性当作必然性。"}
        first = node_choice_request(graph, node)
        self.assertEqual(bundle_for_request(first)["answer_mode"], "support_request")
        register_generated(first["scope"], {"prompt": first["prompt"], "options": [
            {"id": "A", "text": "1/2"}, {"id": "B", "text": "1"}, {"id": "C", "text": "0"}],
            "answer_key": "A", "origin": "model_generated", "answer_mode": "recognition"})
        generated = bundle_for_request(first)
        self.assertEqual(generated["origin"], "model_generated")
        self.assertEqual(len(generated["option_set_id"]), 24)
        changed = copy.deepcopy(node)
        changed["expected_answer"] = "正反两种等可能结果，正面概率 1/2。"
        self.assertNotEqual(first["scope"], node_choice_request(graph, changed)["scope"])
        generated["options"][0]["text"] = "tampered"
        self.assertEqual(bundle_for_request(first)["options"][0]["text"], "1/2")

    def test_selection_is_distinct_from_optional_original_explanation(self):
        bundle = build_choice_bundle("2+2=?", existing_options=[
            {"id": "A", "text": "4"}, {"id": "B", "text": "5"}], answer_key="A", scope="arithmetic")
        question = public_bundle(bundle)
        record = selected_response(question, {"choice_id": "A", "option_set_id": question["option_set_id"], "text": ""})
        self.assertEqual(record["text"], "所选答案：4")
        self.assertEqual(record["free_text"], "")
        self.assertEqual(record["selection"]["options"], bundle["options"])
        self.assertNotIn("answer_key", record["selection"])
        with self.assertRaises(CourseGraphError):
            selected_response(question, {"choice_id": "A", "option_set_id": "changed"})
        with self.assertRaises(CourseGraphError):
            selected_response(question, {"choice_id": "C", "text": "optional explanation"})


if __name__ == "__main__":
    unittest.main()
