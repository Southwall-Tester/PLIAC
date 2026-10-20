"""Isolated synthetic contracts for dialogue, profile provenance and adaptation."""
import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from fastapi.testclient import TestClient
from learning_agent import api
from learning_agent.course_graph import CourseGraphStore, CourseGraphError
from learnmargin.models import APIConfig
from learnmargin.provider import ProviderError
from learnmargin.storage import atomic_json
from pliac.main import app
from pliac import assistant, assistant_profile as profiles, margin
from pliac.assistant_context import clean_context, context_for
from build_linux_course import DEST, COURSE_ID
from install_course_draft import install

CONFIG = APIConfig(base_url="http://127.0.0.1:9999/v1", api_key="synthetic-key", model="synthetic")


def reply(text="合成回答", **kwargs):
    return profiles.TutorReply(answer=text, **kwargs)


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CourseGraphStore(output_dir=Path(self.temp.name) / "store")
        self.enterContext(patch.object(api, "store", self.store))
        self.enterContext(patch.object(assistant, "configured_api", return_value=CONFIG))
        self.enterContext(patch.object(assistant.ChatProvider, "chat", return_value=reply()))
        self.enterContext(patch.object(app.state, "auth_required", False, create=True))
        self.client = self.enterContext(TestClient(app))
        self.owner = uuid.uuid4().hex
        self.conversation = self.client.post("/api/assistant/conversations", json={"owner":self.owner}).json()["id"]

    def send(self, message="你好", context=None, request_id=None):
        return self.client.post(f"/api/assistant/conversations/{self.conversation}/messages",
                                json=dict(owner=self.owner, message=message, request_id=request_id or uuid.uuid4().hex,
                                          context=context or {}))

    def wait(self):
        for _ in range(100):
            result = self.client.get(f"/api/assistant/conversations/{self.conversation}", params={"owner":self.owner}).json()
            if result["status"] != "running":
                return result
            time.sleep(.02)
        self.fail("synthetic answer did not finish")

    def profile(self):
        return self.client.get("/api/assistant/profile",params={"owner":self.owner}).json()

    def test_roundtrip_history_and_owner_isolation(self):
        self.assertEqual(self.send().status_code, 200)
        data = self.wait()
        self.assertEqual([m["role"] for m in data["messages"]], ["user", "assistant"])
        response = self.client.get(f"/api/assistant/conversations/{self.conversation}",
                                   params={"owner":uuid.uuid4().hex})
        self.assertEqual(response.status_code,404)
        self.assertFalse((self.store.output_dir/"learners").exists())

    def test_idempotent_send_does_not_duplicate_model_call(self):
        request_id = uuid.uuid4().hex
        self.send(request_id=request_id);self.wait();self.send(request_id=request_id)
        self.assertEqual(len(self.wait()["messages"]),2)
        self.assertEqual(assistant.ChatProvider.chat.call_count,1)

    def test_profile_changes_next_conversation_prompt(self):
        result = reply(profile_updates=[dict(category="preference",slot="detail",value="先简短结论再举例",
                      quote="请先简短结论再举例",basis="explicit")])
        assistant.ChatProvider.chat.return_value=result
        self.send("请先简短结论再举例");self.wait()
        self.assertEqual(self.profile()["items"][0]["value"],"先简短结论再举例")
        self.conversation=self.client.post("/api/assistant/conversations",json={"owner":self.owner}).json()["id"]
        assistant.ChatProvider.chat.return_value=reply()
        self.send("解释缓存");self.wait()
        context=assistant.ChatProvider.chat.call_args.args[1]
        self.assertEqual(context["personalization"]["preferences"][0]["value"],"先简短结论再举例")

    def test_unattributed_profile_and_unknown_diagnosis_are_discarded(self):
        assistant.ChatProvider.chat.return_value=reply(profile_updates=[
            dict(category="interest",slot="topic",value="物理",quote="我喜欢物理",basis="inferred")],
            diagnosis=[dict(concept_id="invented",quote="你好",signal="misconception",reason="synthetic",
                            check_question="why",source_ids=["S99"])])
        self.send();data=self.wait()
        self.assertEqual(data["messages"][-1]["diagnosis"],[])
        self.assertEqual(self.profile()["items"],[])

    def test_evidence_backed_diagnosis_updates_followup_context(self):
        install(DEST/"course.json",self.store)
        context=dict(course_id=COURSE_ID,node_id="shell")
        assistant.ChatProvider.chat.return_value=reply(diagnosis=[
            dict(concept_id="shell",quote="终端就是内核",signal="misconception",reason="混淆终端和内核",
                 check_question="Shell 在哪一步参与？",source_ids=["S1"])])
        self.send("终端就是内核",context);self.wait()
        self.assertEqual(self.profile()["concepts"][0]["signal"],"misconception")
        assistant.ChatProvider.chat.return_value=reply(diagnosis=[
            dict(concept_id="shell",quote="终端提供交互，Shell解释命令",signal="correct",reason="正确区分了二者",
                 check_question="换一个命令解释流程。",source_ids=["S1"])])
        self.send("终端提供交互，Shell解释命令",context);self.wait()
        self.assertEqual(self.profile()["concepts"][0]["signal"],"correct")
        self.assertEqual(assistant.ChatProvider.chat.call_args.args[1]["personalization"]["learning_focus"][0]["signal"],
                         "misconception")

    def test_stop_retry_and_duplicate_busy_request(self):
        async def slow(*_):
            await asyncio.sleep(30)
            return reply()
        assistant.ChatProvider.chat.side_effect=slow
        self.send()
        self.assertEqual(self.send("另一个问题").status_code,409)
        stopped=self.client.post(f"/api/assistant/conversations/{self.conversation}/stop",json={"owner":self.owner})
        self.assertEqual(stopped.json()["status"],"cancelled")
        assistant.ChatProvider.chat.side_effect=None
        self.client.post(f"/api/assistant/conversations/{self.conversation}/retry",json={"owner":self.owner})
        self.assertEqual(self.wait()["status"],"idle")

    def test_user_edits_and_disable_win_over_generated_memories(self):
        assistant.ChatProvider.chat.return_value=reply(profile_updates=[
            dict(category="preference",slot="detail",value="详细讲解",quote="详细讲解",basis="explicit")])
        self.send("详细讲解");self.wait()
        ident=self.profile()["items"][0]["id"]
        self.client.post("/api/assistant/profile",json=dict(owner=self.owner,action="edit",id=ident,value="先给结论"))
        self.send("详细讲解");self.wait()
        self.assertEqual(self.profile()["items"][0]["value"],"先给结论")
        self.client.post("/api/assistant/profile",json=dict(owner=self.owner,action="delete",id=ident))
        self.send("详细讲解");self.wait()
        self.assertEqual(self.profile()["items"],[])
        self.client.post("/api/assistant/profile",json=dict(owner=self.owner,action="toggle",enabled=False))
        self.send();self.wait()
        self.assertEqual(assistant.ChatProvider.chat.call_args.args[1]["personalization"]["preferences"],[])

    def test_invalid_path_and_cross_origin_rejected(self):
        self.assertEqual(self.client.get("/api/assistant/profile",params={"owner":"../escape"}).status_code,400)
        self.assertEqual(self.client.post("/api/assistant/conversations",json={"owner":self.owner},
                                         headers={"Origin":"https://example.org"}).status_code,403)

    def test_memory_recalls_original_detail_across_conversations_and_is_editable(self):
        assistant.ChatProvider.chat.return_value=reply(memory_note=dict(
            summary="决定实验输出的位置",quote="实验输出目录",domain="coding",subject="实验输出"))
        self.send("实验输出目录是 /tmp/alpha42/result.json，留到下一次讨论。");self.wait()
        entries=self.client.get("/api/assistant/memory",params={"owner":self.owner}).json()["entries"]
        self.assertEqual(len(entries),1)
        self.assertNotIn("alpha42",entries[0]["summary"])
        self.conversation=self.client.post("/api/assistant/conversations",json={"owner":self.owner}).json()["id"]
        assistant.ChatProvider.chat.return_value=reply()
        self.send("alpha42 的结果放在哪个路径？");data=self.wait()
        memory=assistant.ChatProvider.chat.call_args.args[1]["memory"]
        self.assertIn("/tmp/alpha42/result.json",json.dumps(memory,ensure_ascii=False))
        self.assertLessEqual(data["messages"][-1]["memory_usage"]["selected_chars"],28000)
        self.assertTrue(data["messages"][-1]["memory_references"])
        response=self.client.post("/api/assistant/memory",json={
            "owner":self.owner,"action":"edit","id":entries[0]["id"],"value":"实验输出已经改到 /srv/new"})
        self.assertEqual(response.status_code,200)
        modified=response.json()["memory"]["entries"]
        self.assertTrue(next(i for i in modified if i["id"]==entries[0]["id"])["edited"])
        self.client.post("/api/assistant/memory",json={"owner":self.owner,"action":"delete","id":entries[0]["id"]})
        remaining=self.client.get("/api/assistant/memory",params={"owner":self.owner}).json()["entries"]
        self.assertNotIn(entries[0]["id"],[i["id"] for i in remaining])
        self.assertEqual(self.client.get("/api/assistant/memory",params={"owner":uuid.uuid4().hex}).json()["entries"],[])

    def test_disabled_personalization_does_not_store_or_recall_task_memory(self):
        self.client.post("/api/assistant/profile",json=dict(owner=self.owner,action="toggle",enabled=False))
        self.send("实验输出目录是 /tmp/alpha42/result.json");self.wait()
        self.assertEqual(self.client.get("/api/assistant/memory",params={"owner":self.owner}).json()["entries"],[])
        context=assistant.ChatProvider.chat.call_args.args[1]
        self.assertEqual(context["memory"]["summaries"],[])

    def test_null_memory_note_preserves_chat_without_cross_conversation_indexing(self):
        assistant.ChatProvider.chat.return_value = reply("本轮信息保留在当前对话。", memory_note=None)
        raw = "本次讨论的 glacier-731 路径是 /tmp/transient，不记入长期记忆。"
        self.assertEqual(self.send(raw).status_code, 200)
        data = self.wait()
        self.assertEqual([item["content"] for item in data["messages"]],
                         [raw, "本轮信息保留在当前对话。"])
        self.assertEqual(data["messages"][-1]["episode_updates"], [])
        self.assertEqual(self.client.get("/api/assistant/memory",
                         params={"owner": self.owner}).json()["entries"], [])
        self.conversation = self.client.post("/api/assistant/conversations",
                                            json={"owner": self.owner}).json()["id"]
        self.send("glacier-731 的路径是什么？")
        self.wait()
        context = assistant.ChatProvider.chat.call_args.args[1]
        self.assertEqual(context["memory"]["summaries"], [])
        self.assertEqual(context["memory"]["residuals"], [])

    def test_current_selection_retrieves_matching_concept(self):
        install(DEST/"course.json",self.store)
        value=context_for(clean_context(dict(course_id=COURSE_ID,node_id="chmod")),"这个怎么用")
        self.assertEqual(value["references"][0]["concept_id"],"chmod")
        self.assertIn("prerequisites",value["references"][0]["text"])

    def test_personal_handout_context_uses_authenticated_student_on_send_and_retry(self):
        install(DEST / "course.json", self.store)
        course = api.resolve_course_store(COURSE_ID)
        handouts = margin.storage(course)
        with patch.dict(app.state._state, {"auth_required": True,
                                          "account_directory": Path(self.temp.name) / "accounts"}):
            victim = self.client.post("/api/account/register", json={
                "username": "victim-account", "password": "synthetic-password"}).json()["user"]
            self.client.post("/api/account/logout")
            own = self.client.post("/api/account/register", json={
                "username": "requesting-account", "password": "synthetic-password"}).json()["user"]
            self.owner = own["assistant_owner"]
            self.conversation = self.client.post("/api/assistant/conversations", json={}).json()["id"]
            jobs = {}
            for name, student in (("own", own["student_id"]), ("foreign", victim["student_id"])):
                ident = uuid.uuid4().hex
                handouts.save_job(dict(id=ident, student_id=student, status="completed",
                    created_at="2026-10-20", course_id=COURSE_ID, course_version=margin.graph_for(course)[0]["version"]))
                folder = handouts.directory("jobs", ident)
                atomic_json(folder / "lesson.json", {"sections": [
                    {"id": "s1", "title": "私有教学策略", "explanation": name + "_PRIVATE_LESSON"}]})
                atomic_json(folder / "knowledge-map.json", {"nodes": [], "edges": []})
                jobs[name] = clean_context(dict(course_id=COURSE_ID, job_id=ident))
            own_context = context_for(jobs["own"], "私有教学策略", own["student_id"])
            self.assertIn("own_PRIVATE_LESSON", json.dumps(own_context))
            for student in ("", victim["student_id"]):
                with self.assertRaises(CourseGraphError):
                    context_for(jobs["own"], "私有教学策略", student)
            denied = self.send("读取私有教学策略", jobs["foreign"])
            self.assertEqual(404, denied.status_code)
            assistant.ChatProvider.chat.assert_not_called()
            with patch.object(assistant, "context_for", wraps=context_for) as context_reader:
                assistant.ChatProvider.chat.side_effect = ProviderError("合成失败以核验重试身份")
                self.assertEqual(200, self.send("读取私有教学策略", jobs["own"]).status_code)
                self.assertEqual("failed", self.wait()["status"])
                self.assertEqual(own["student_id"], context_reader.call_args.args[2])
                # Retry must re-bind the cookie identity even if an older saved
                # conversation retained an obsolete student identifier.
                saved = assistant.read(self.owner, self.conversation)
                saved["student_id"] = "obsolete-student"
                assistant.save(self.owner, saved)
                assistant.ChatProvider.chat.side_effect = None
                retried = self.client.post(f"/api/assistant/conversations/{self.conversation}/retry",
                                          json={"owner": self.owner})
                self.assertEqual(200, retried.status_code)
                self.assertEqual("idle", self.wait()["status"])
                self.assertEqual(own["student_id"], context_reader.call_args.args[2])
                actual_context = assistant.ChatProvider.chat.call_args.args[1]
                self.assertIn("own_PRIVATE_LESSON", json.dumps(actual_context))
                self.assertNotIn("foreign_PRIVATE_LESSON", json.dumps(actual_context))


class ProfileAlgorithmTests(unittest.TestCase):
    def test_bm25_works_across_unrelated_topics(self):
        for query,documents,target in [
            ("缓存一致性",["缓存一致性与多核处理器","Linux 的文件权限"],0),
            ("chmod 权限",["二叉树遍历","chmod 文件权限与用户"],1),
            ("photosynthesis",["photosynthesis in plants","shell command"],0)]:
            scores=profiles.rank_documents(query,documents)
            self.assertEqual(max(range(len(scores)),key=scores.__getitem__),target)

    def test_explicit_preference_replaces_old_value_and_records_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);context={"references":[]}
            for text in ("讲详细些","只讲结论"):
                result=reply(profile_updates=[dict(category="preference",slot="detail",value=text,quote=text,basis="explicit")])
                profiles.apply(folder,result,dict(id=uuid.uuid4().hex,content=text),context,"synthetic",
                               profiles.load(folder)["revision"])
            data=profiles.load(folder)
            self.assertEqual([i["value"] for i in data["items"] if i["active"]],["只讲结论"])
            self.assertEqual(len(data["items"]),2)

    def test_recency_decay_and_inflight_revision(self):
        item=dict(category="interest",basis="inferred",updated_at="2000-01-01T00:00:00+00:00",observations=1)
        self.assertLess(profiles.weight(item),.001)
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);profile=profiles.load(folder);profiles.save(folder,profile)
            result=reply(profile_updates=[dict(category="interest",slot="topic",value="物理",quote="喜欢物理",basis="explicit")])
            profiles.apply(folder,result,dict(id="a",content="喜欢物理"),{"references":[]},"x",0)
            self.assertEqual(profiles.load(folder)["items"],[])


if __name__ == "__main__":
    unittest.main()
