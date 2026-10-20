"""Behavioral checks for bounded, editable conversation-memory retrieval."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import uuid

from pliac import assistant_memory as memory


def message(role, content, course="", document=""):
    return dict(id=uuid.uuid4().hex, role=role, content=content, status="complete",
                context=dict(course_id=course, document_id=document),
                created_at="2026-10-20T10:00:00+00:00")


def conversation(*messages):
    return dict(id=uuid.uuid4().hex, messages=list(messages), created_at="2026-10-20T10:00:00+00:00")


def note(summary, quote, domain="learning", **kwargs):
    return SimpleNamespace(memory_note=dict(summary=summary, quote=quote, domain=domain,
                                           subject=kwargs.pop("subject", summary[:100]), **kwargs))


class AssistantMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.folder = Path(self.temp.name) / "owner"
        self.folder.mkdir()
        self.addCleanup(self.temp.cleanup)

    def save(self, data):
        (self.folder / f"{data['id']}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def remember(self, data, reply=None):
        self.save(data)
        if reply is None:
            content = data["messages"][0]["content"]
            reply = note(content[:400], content[:600])
        return memory.remember(self.folder, data, data["messages"][0], reply,
                               memory.load(self.folder)["revision"])

    def prepare(self, question, course="linux", document="", **kwargs):
        current = conversation(message("user", question, course, document))
        return memory.prepare(self.folder, current, dict(course_id=course, document_id=document), **kwargs)

    def test_recovers_original_detail_missing_from_summary(self):
        raw = "我准备练习 Shell 自动化。" + "继续准备学习。" * 250 + "部署目录是 /srv/nebula-731，每日清理脚本叫 prune_cache.sh。"
        old = conversation(message("user", raw, "linux"), message("assistant", "可以安排脚本练习。"))
        self.remember(old, note("学习 Shell 自动化。", "我准备练习 Shell 自动化。"))
        _, context, metrics = self.prepare("nebula-731 的部署目录和清理脚本叫什么？")
        self.assertTrue(any("/srv/nebula-731" in row["text"] and "prune_cache.sh" in row["text"] for row in context["residuals"]))
        self.assertEqual(context["summaries"][0]["summary"], "学习 Shell 自动化。")
        self.assertGreater(metrics["recalled_count"], 0)
        persisted = (self.folder / "memory/current.json").read_text(encoding="utf-8")
        self.assertNotIn("/srv/nebula-731", persisted)
        self.assertNotIn("prune_cache.sh", persisted)
        self.assertEqual(context["residuals"][0]["source"]["conversation_id"], old["id"])

    def test_recent_complete_turns_continue_past_huge_answer(self):
        good_user, good_answer = message("user", "先讨论工作目录", "linux"), message("assistant", "目录可用 pwd 查看。")
        last = message("user", "需要保留的最新完整问题。" * 300, "linux")
        data = conversation(good_user, good_answer, message("user", "很长的解释", "linux"),
                            message("assistant", "长回答" * 16000), last)
        messages, context, metrics = memory.prepare(self.folder, data, {"course_id": "linux"})
        self.assertEqual(messages[-1]["content"], last["content"])
        self.assertIn(good_user["content"], [item["content"] for item in messages])
        self.assertIn(good_answer["content"], [item["content"] for item in messages])
        self.assertLessEqual(metrics["selected_chars"], 28000)
        self.assertEqual(metrics["selected_chars"],
                         len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(context, ensure_ascii=False)))

    def test_many_related_candidates_respect_serialized_sub_budgets(self):
        for number in range(18):
            raw = f'archive_rotation_{number} 的备份记录。路径包含 "\\\\cache"。\n' * 45
            old = conversation(message("user", raw, "linux"),
                               message("assistant", f"archive_rotation_{number} 执行周期需要检查。" * 80))
            self.remember(old)
        messages, context, metrics = self.prepare("备份记录和执行周期要怎么检查？")
        self.assertGreater(metrics["summary_count"], 0)
        self.assertGreater(metrics["residual_count"], 0)
        self.assertLessEqual(len(json.dumps(context["summaries"], ensure_ascii=False)), memory.SUMMARY_BUDGET)
        self.assertLessEqual(len(json.dumps(context["residuals"], ensure_ascii=False)), memory.RESIDUAL_BUDGET)
        self.assertLessEqual(metrics["selected_chars"], memory.BUDGET)
        self.assertEqual(metrics["selected_chars"],
                         len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(context, ensure_ascii=False)))

    def test_cross_owner_course_document_and_general_isolation(self):
        old = conversation(message("user", "课程资料的星云编号是 NEBULA-731。", "linux", "doc-a"))
        self.remember(old)
        for course, document in (("physics", ""), ("linux", "doc-b"), ("", "")):
            _, ctx, _ = self.prepare("NEBULA-731 的星云编号？", course, document)
            self.assertEqual(ctx["residuals"], [])
            self.assertEqual(ctx["summaries"], [])
        other = self.folder.parent / "other-owner"
        data = conversation(message("user", "NEBULA-731", "linux", "doc-a"))
        _, ctx, _ = memory.prepare(other, data, {"course_id": "linux", "document_id": "doc-a"})
        self.assertEqual(ctx["summaries"], [])
        _, ctx, _ = self.prepare("NEBULA-731", "linux", "doc-a")
        self.assertEqual(len(ctx["summaries"]), 1)

    def test_disabled_avoids_reading_index_and_old_turn_retrieval(self):
        old = conversation(message("user", "备份名是 mirror_backup。", "linux"))
        self.remember(old)
        index = self.folder / "memory/current.json"
        before = index.read_bytes()
        _, ctx, metrics = self.prepare("mirror_backup", enabled=False)
        self.assertFalse(ctx["summaries"])
        self.assertFalse(metrics["personalization_enabled"])
        self.assertEqual(index.read_bytes(), before)
        index.write_text("invalid json proves prepare does not read it", encoding="utf-8")
        _, ctx, _ = self.prepare("mirror_backup", enabled=False)
        self.assertFalse(ctx["residuals"])

    def test_edit_delete_and_inflight_revision_never_restore_original(self):
        old = conversation(message("user", "发布服务器代号是 oldcluster-x7。", "linux"))
        ident = self.remember(old)[0]
        old_revision = memory.load(self.folder)["revision"]
        state = memory.edit(self.folder, "edit", ident, "发布服务器改成 newcluster-y8。")
        self.assertTrue(state["entries"][0]["edited"])
        self.assertIn("oldcluster-x7", state["entries"][0]["quote"])  # UI provenance
        _, ctx, _ = self.prepare("oldcluster-x7")
        self.assertFalse(ctx["summaries"])
        self.assertFalse(ctx["residuals"])
        _, ctx, _ = self.prepare("newcluster-y8")
        self.assertEqual(ctx["summaries"][0]["summary"], "发布服务器改成 newcluster-y8。")
        self.assertFalse(ctx["residuals"])
        old["messages"].extend([message("assistant", "发布到 oldcluster-x7。"),
                                message("user", "newcluster-y8 怎么发布？", "linux")])
        messages, ctx, _ = memory.prepare(self.folder, old, {"course_id": "linux"})
        self.assertEqual(len(messages), 1)
        self.assertEqual(ctx["summaries"][0]["summary"], "发布服务器改成 newcluster-y8。")
        newer = conversation(message("user", "newcluster-y8 继续部署", "linux"))
        self.assertEqual(memory.remember(self.folder, newer, newer["messages"][0], SimpleNamespace(), old_revision), [])
        memory.edit(self.folder, "delete", ident)
        self.assertFalse(memory.view(self.folder)["entries"])
        # Deleting the index entry also excludes legacy fallback of this turn.
        old["messages"].extend([message("assistant", "冗长回复" * 8000), message("user", "oldcluster-x7", "linux")])
        _, ctx, _ = memory.prepare(self.folder, old, {"course_id": "linux"})
        self.assertFalse(ctx["summaries"])
        self.assertFalse(ctx["residuals"])
        self.assertEqual(memory.remember(self.folder, old, old["messages"][0], SimpleNamespace(),
                                         memory.load(self.folder)["revision"]), [])

    def test_revisions_are_scoped_and_user_edits_win(self):
        old = conversation(message("user", "任务 alpha 的实现语言先用 Python。", "linux"))
        old_id = self.remember(old, note("alpha 用 Python", "先用 Python"))[0]
        foreign = conversation(message("user", "任务 alpha 在物理课使用 Python。", "physics"))
        foreign_id = self.remember(foreign, note("alpha 用 Python", "使用 Python"))[0]
        newer = conversation(message("user", "任务 alpha 改成 Rust。", "linux"))
        new_id = self.remember(newer, note("alpha 改成 Rust", "改成 Rust", supersedes=[old_id, foreign_id]))[0]
        entries = memory.view(self.folder)["entries"]
        self.assertNotIn(old_id, [item["id"] for item in entries])
        self.assertIn(foreign_id, [item["id"] for item in entries])
        self.assertEqual(memory.view(self.folder)["history_count"], 1)
        memory.edit(self.folder, "edit", new_id, "alpha 明确改成 Go")
        third = conversation(message("user", "任务 alpha 又用 Java。", "linux"))
        self.remember(third, note("alpha 用 Java", "又用 Java", supersedes=[new_id]))
        self.assertIn(new_id, [item["id"] for item in memory.view(self.folder)["entries"]])

    def test_unrelated_topics_and_english_chinese_retrieval(self):
        chinese = conversation(message("user", "递归练习选汉诺塔，约束参数是塔高七层。", "linux"))
        english = conversation(message("user", "Deployment uses rotating credentials and sentinel_watchdog.", "linux"),
                               message("assistant", "The sentinel_watchdog is checked every 17 minutes."))
        self.remember(chinese)
        self.remember(english)
        _, unrelated, _ = self.prepare("What is the photosynthesis wavelength?")
        self.assertFalse(unrelated["summaries"])
        _, chinese_result, _ = self.prepare("汉诺塔的塔高是几层？")
        self.assertTrue(any("七层" in row["text"] for row in chinese_result["residuals"]))
        _, english_result, _ = self.prepare("sentinel_watchdog checked how often?")
        self.assertTrue(any(row["model_generated"] and "17 minutes" in row["text"] for row in english_result["residuals"]))

    def test_null_missing_or_invalid_note_never_creates_long_term_memory(self):
        valid = dict(summary="整理 glacier.dat", quote="原始文件是 glacier.dat",
                     domain="learning", subject="原始文件")
        invalid = [
            SimpleNamespace(memory_note=None),
            SimpleNamespace(),  # Legacy replies do not opt into a new index entry.
            {},
            note("伪造用户拥有火星基地", "从未说过的话"),
            SimpleNamespace(memory_note={key: value for key, value in valid.items() if key != "quote"}),
            SimpleNamespace(memory_note=valid | {"domain": ["learning"]}),
            SimpleNamespace(memory_note=valid | {"summary": " "}),
            SimpleNamespace(memory_note=valid | {"subject": " "}),
            SimpleNamespace(memory_note=valid | {"quote": "  "}),
        ]
        for reply in invalid:
            with self.subTest(reply=reply):
                old = conversation(message("user", "本次内容不记入长期记忆，原始文件是 glacier.dat。", "linux"))
                self.save(old)
                transcript = self.folder / f"{old['id']}.json"
                before = transcript.read_bytes()
                self.assertEqual(self.remember(old, reply), [])
                self.assertEqual(memory.view(self.folder)["entries"], [])
                self.assertEqual(memory.load(self.folder)["revision"], 0)
                self.assertFalse((self.folder / "memory/current.json").exists())
                self.assertEqual(transcript.read_bytes(), before)
                _, ctx, _ = self.prepare("glacier.dat 原始文件")
                self.assertFalse(ctx["summaries"])
                self.assertFalse(ctx["residuals"])

    def test_legacy_details_remain_retrievable_in_current_conversation_without_indexing(self):
        data = conversation(message("user", "旧版对话包含 legacy_daemon 配置", "linux"),
                            message("assistant", "冗长回复" * 8000),
                            message("user", "legacy_daemon 配置在哪？", "linux"))
        _, ctx, _ = memory.prepare(self.folder, data, {"course_id": "linux"})
        self.assertTrue(any("旧版对话" in row["text"] for row in ctx["residuals"]))
        self.assertFalse((self.folder / "memory/current.json").exists())

    def test_recent_turns_are_not_repeated_in_memory_and_course_switch_filters(self):
        old = message("user", "stellar_kernel 的参数是 42", "linux")
        data = conversation(old, message("assistant", "stellar_kernel 使用 42"),
                            message("user", "stellar_kernel 怎么用？", "linux"))
        self.remember(data)
        messages, ctx, _ = memory.prepare(self.folder, data, {"course_id": "linux"})
        self.assertEqual(len(messages), 3)
        self.assertFalse(ctx["summaries"])
        self.assertFalse(ctx["residuals"])
        data["messages"].append(message("user", "stellar_kernel", "physics"))
        messages, ctx, _ = memory.prepare(self.folder, data, {"course_id": "physics"})
        self.assertEqual(len(messages), 1)
        self.assertFalse(ctx["summaries"])

    def test_source_path_cannot_escape_owner_folder(self):
        data = conversation(message("user", "不能写到其他目录", "linux"))
        data["id"] = "../escape"
        self.assertEqual(memory.remember(self.folder, data, data["messages"][0], SimpleNamespace(), 0), [])
        self.assertFalse((self.folder / "memory").exists())


if __name__ == "__main__":
    unittest.main()
