"""Synthetic, isolated tests. Run: python tests/test_course_graph.py"""
import copy
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent.course_graph import CourseGraphError, CourseGraphStore, validate_graph


def fixture():
    nodes = [{"id": i, "title": i, "chapter_id": "ch1" if i in "ab" else "ch2", "description": "概念说明",
              "objectives": ["能独立解释"], "misconception": "典型误解", "aliases": [], "source_ids": ["book"], "review_status": "draft"} for i in "abcd"]
    edges = [{"id": a+b, "source": a, "target": b, "type": kind, "reason": "教学关系", "source_ids": ["book"], "review_status": "draft"}
             for a,b,kind in [("a","c","prerequisite"),("b","c","prerequisite"),("c","d","prerequisite"),("d","a","confusable")]]
    return {"schema_version": 1, "id": "ml_classification", "version": 1, "title": "合成测试课程",
            "chapters": [{"id": c, "title": c, "description": ""} for c in ("ch1","ch2")],
            "sources": [{"id": "book", "title": "测试资料", "kind": "test", "url": "https://example.com/book"}], "nodes": nodes, "edges": edges,
            "resources": [{"id": "r_a", "title": "测试讲解", "organization": "测试机构", "url": "https://example.com/lesson", "node_ids": ["a"],
                           "applicable_segment": "第一节", "prerequisite_ids": [], "format": "lesson", "review_status": "draft"}],
            "review_policy": {"intervals_days": [1,7,30]}}


class CourseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.seed = self.base / "seed.json"
        self.graph = fixture(); self.seed.write_text(json.dumps(self.graph,ensure_ascii=False),encoding="utf-8")
        self.seed_bytes = self.seed.read_bytes(); self.now = datetime(2026,10,8,tzinfo=timezone.utc)
        self.store = CourseGraphStore(self.seed,self.base/"outputs",clock=lambda:self.now)

    def publish(self, graph=None):
        graph = copy.deepcopy(graph or self.store.load_graph("draft"))
        for item in [*graph["nodes"],*graph["edges"],*graph["resources"]]:
            item.update(review_status="reviewed",reviewer="Synthetic reviewer",reviewed_at=self.now.isoformat(),review_note=f"Synthetic review {graph['version']}")
        graph = self.store.save_graph(graph,graph["version"])["graph"]
        self.store.publish(graph["version"],"Synthetic publisher","合成测试发布")
        return graph

    def evidence(self, node_id="a", student_id="s1", **changes):
        data = {"student_id":student_id,"node_id":node_id,"course_version":self.store.load_graph()["version"],"source_type":"quiz",
                "origin":"learner_expression","prompt_level":0,"text":"学习者的独立作答","context":{"task_id":"task1","task_version":1,"turn_id":1}}
        data.update(changes)
        return self.store.add_evidence(data)

    def diagnose(self, raw, status="mastered", **changes):
        e = raw["evidence"]
        data = {"student_id":e["student_id"],"node_id":e["node_id"],"course_version":e["course_version"],"evidence_ids":[e["id"]],
                "status":status,"basis":"合成测试判断依据","review_status":"reviewed","reviewer":"Synthetic reviewer","is_retest":False}
        data.update(changes)
        return self.store.add_diagnosis(data)

    def test_unpublished_view_is_clear_and_preview_is_not_formal(self):
        self.assertIsNone(self.store.view("s1")["graph"])
        self.assertTrue(self.store.view("s1","draft")["learner"]["preview_only"])
        self.assertFalse(self.store.output_dir.exists())
        with self.assertRaises(CourseGraphError): self.store.load_graph("published",1)

    def test_publication_requires_reviewed_assets_and_metadata(self):
        with self.assertRaises(CourseGraphError): self.store.publish(1,"Test","Test")
        bad=copy.deepcopy(self.graph); bad["nodes"][0]["review_status"]="reviewed"
        with self.assertRaises(CourseGraphError): validate_graph(bad)
        graph=self.publish(); graph["resources"][0]["review_status"]="draft"
        self.store.save_graph(graph,2)
        with self.assertRaises(CourseGraphError): self.store.publish(3,"Test","Test")

    def test_semantic_edits_invalidate_stale_review_and_keep_published(self):
        graph=self.publish()
        graph["nodes"][0]["description"]="新定义"
        graph["edges"][0]["reason"]="新关系依据"
        graph["resources"][0]["applicable_segment"]="第二节"
        saved=self.store.save_graph(graph,2)["graph"]
        for group in ("nodes","edges","resources"):
            self.assertEqual(saved[group][0]["review_status"],"draft")
            self.assertNotIn("reviewer",saved[group][0])
        with self.assertRaises(CourseGraphError): self.store.publish(3,"Test","Test")
        self.assertEqual(self.store.load_graph()["version"],2)
        self.assertEqual(self.seed.read_bytes(),self.seed_bytes)

    def test_uncommitted_publication_is_not_a_published_version(self):
        from learning_agent import course_graph as module
        graph=self.publish(); self.store.save_graph(graph,2)
        original=module._atomic_json
        def fail(path,data):
            if path.name=="publication.json": raise OSError("synthetic failure")
            return original(path,data)
        with patch.object(module,"_atomic_json",side_effect=fail):
            with self.assertRaises(OSError): self.store.publish(3,"Test","Test")
        with self.assertRaises(CourseGraphError): self.store.load_graph("published",3)
        self.assertEqual(self.store.load_graph()["version"],2)

    def test_confusable_is_nondirectional_and_ordering_edges_are_acyclic(self):
        validate_graph(self.graph)
        for kind in ("prerequisite","contains"):
            bad=copy.deepcopy(self.graph)
            bad["edges"]=[dict(bad["edges"][0],id="ac",source="a",target="c",type=kind),dict(bad["edges"][0],id="ca",source="c",target="a",type=kind)]
            with self.assertRaises(CourseGraphError): validate_graph(bad)
        bad=copy.deepcopy(self.graph); bad["edges"].append(dict(bad["edges"][-1],id="ad",source="a",target="d"))
        with self.assertRaises(CourseGraphError): validate_graph(bad)

    def test_bad_paths_urls_and_dangling_edges_rejected(self):
        for bad in ("../x","CON","a/b","x\\y","x"*65):
            with self.assertRaises(CourseGraphError): self.store.load_learner(bad)
        for url in ("javascript:alert(1)","file:///x","https://u:p@example.com","https://example.com:bad"):
            bad=copy.deepcopy(self.graph); bad["sources"][0]["url"]=url
            with self.assertRaises(CourseGraphError): validate_graph(bad)
        bad=copy.deepcopy(self.graph); bad["edges"][0]["target"]="missing"
        with self.assertRaises(CourseGraphError): validate_graph(bad)

    def test_optional_teaching_fields_are_validated_and_answers_hidden(self):
        graph=copy.deepcopy(self.graph); graph["nodes"][0].update(check_question="题目",expected_answer="教师答案",check_task={"id":"task1","version":1,"rubric":["判据"],"hint_levels":["一","二","三","四"]})
        for field in ("check_question","expected_answer"):
            for value in ({"toString":None},"x"*4001,None):
                bad=copy.deepcopy(graph); bad["nodes"][0][field]=value
                with self.assertRaises(CourseGraphError): validate_graph(bad)
        self.publish(graph); public=self.store.view()["graph"]["nodes"][0]
        self.assertNotIn("expected_answer",public); self.assertNotIn("rubric",public["check_task"]); self.assertNotIn("hint_levels",public["check_task"])
        self.assertEqual(self.store.view(view="draft")["graph"]["nodes"][0]["expected_answer"],"教师答案")

    def test_raw_evidence_is_uncertain_not_direct_mastery(self):
        self.publish(); result=self.evidence()
        self.assertEqual(result["learner"]["states"]["a"]["status"],"uncertain")
        self.assertEqual(result["learner"]["states"]["b"]["status"],"unknown")
        self.assertNotIn("status",result["evidence"])
        self.assertEqual(result["evidence"]["context"]["task_version"],1)
        with self.assertRaises(CourseGraphError): self.evidence(status="mastered")

    def test_expressed_relations_preserve_origin_without_changing_course_order(self):
        published=self.publish()
        relation={"source":"a","target":"d","relation":"我认为两者相反","quote":"a 与 d 相反"}
        for origin in ("learner_expression","system_completion","model_inference"):
            raw=self.evidence(student_id=origin,origin=origin,text="我的解释：a 与 d 相反。",expressed_relations=[relation])
            record=self.store.load_learner(origin)["evidence"][0]
            self.assertEqual(record["expressed_relations"],[relation]); self.assertEqual(record["origin"],origin)
            self.assertEqual(record["id"],raw["evidence"]["id"]); self.assertEqual(record["prompt_level"],0)
            self.assertNotEqual(raw["learner"]["states"]["a"]["status"],"mastered")
            self.assertEqual([s["node_id"] for s in self.store.learning_path("d",origin)["steps"]],["a","b","c","d"])
        self.assertEqual(self.store.load_graph(),published)

    def test_expressed_relations_reject_fabricated_quote_and_invalid_endpoints(self):
        self.publish(); relation={"source":"a","target":"d","relation":"相关","quote":"原话"}
        bad_items=[dict(relation,quote="并未说过"),dict(relation,target="missing"),dict(relation,source="b",target="c"),
                   dict(relation,relation=""),dict(relation,relation="x"*201),dict(relation,quote="x"*4001)]
        for item in bad_items:
            with self.assertRaises(CourseGraphError): self.evidence(text="原话",expressed_relations=[item])
        with self.assertRaises(CourseGraphError): self.evidence(text="原话",expressed_relations=[relation]*21)
        self.assertEqual(self.store.load_learner("s1")["evidence"],[])

    def test_system_inference_and_technical_failure_cannot_judge_ability(self):
        self.publish()
        for fields in ({"origin":"system_completion"},{"origin":"model_inference"},{"source_type":"technical"}):
            raw=self.evidence(**fields)
            self.assertEqual(raw["learner"]["states"]["a"]["status"],"unknown")
            for status in ("mastered","needs_review"):
                with self.assertRaises(CourseGraphError): self.diagnose(raw,status)

    def test_self_report_hint_or_unreviewed_judgment_cannot_prove_mastery(self):
        self.publish()
        for fields in ({"source_type":"self_assessment"},{"prompt_level":1},{"prompt_level":4},{"prompt_level":None}):
            raw=self.evidence(**fields)
            with self.assertRaises(CourseGraphError): self.diagnose(raw)
        with self.assertRaises(CourseGraphError): self.diagnose(self.evidence(),review_status="draft",reviewer="")
        for level in (-1,5,True,"0"):
            with self.assertRaises(CourseGraphError): self.evidence(prompt_level=level)

    def test_diagnosis_must_match_evidence_node_and_course_version(self):
        self.publish(); raw=self.evidence()
        with self.assertRaises(CourseGraphError): self.diagnose(raw,node_id="b")
        with self.assertRaises(CourseGraphError): self.diagnose(raw,course_version=999)
        self.assertEqual(self.diagnose(raw)["learner"]["states"]["a"]["status"],"mastered")

    def test_decisive_diagnosis_requires_versioned_supporting_task(self):
        self.publish(); unbound=self.evidence(context={})
        self.assertEqual(unbound["learner"]["states"]["a"]["status"],"uncertain")
        for status in ("mastered","needs_review"):
            with self.assertRaises(CourseGraphError): self.diagnose(unbound,status)
        self.assertEqual(self.diagnose(unbound,"uncertain")["learner"]["states"]["a"]["status"],"uncertain")
        # A bound model response cannot supply the missing context for a real expression.
        generated=self.evidence(origin="system_completion")
        with self.assertRaises(CourseGraphError):
            self.diagnose(unbound,evidence_ids=[unbound["evidence"]["id"],generated["evidence"]["id"]])
        for context in ({"task_id":"task1"},{"task_version":1}):
            with self.assertRaises(CourseGraphError): self.evidence(context=context)

    def test_practice_diagnosis_requires_versioned_skeleton(self):
        self.publish(); raw=self.evidence(source_type="practice")
        for status in ("mastered","needs_review"):
            with self.assertRaises(CourseGraphError): self.diagnose(raw,status)
        self.diagnose(raw,"uncertain")
        bound=self.evidence(source_type="practice",context={"task_id":"practice1","task_version":1,"skeleton_id":"code1","skeleton_version":2})
        result=self.diagnose(bound)
        self.assertEqual(result["learner"]["states"]["a"]["status"],"mastered")
        self.assertEqual(result["learner"]["evidence"][0]["id"],raw["evidence"]["id"])

    def test_conflict_needs_explicit_reviewed_resolution(self):
        self.publish(); first=self.diagnose(self.evidence())
        conflict=self.diagnose(self.evidence(text="作答错误"),"needs_review")
        self.assertEqual(conflict["learner"]["states"]["a"]["status"],"uncertain")
        self.assertIn("冲突",conflict["learner"]["states"]["a"]["reason"])
        resolved=self.diagnose(self.evidence(text="复核确认缺口"),"needs_review",resolves_diagnosis_ids=[first["diagnosis"]["id"]])
        self.assertEqual(resolved["learner"]["states"]["a"]["status"],"needs_review")
        self.assertEqual(len(resolved["learner"]["evidence"]),3)

    def test_interval_review_uses_new_evidence_and_does_not_mark_failure(self):
        self.publish(); raw=self.evidence(); first=self.diagnose(raw)
        self.now+=timedelta(days=2); due=self.store.load_learner("s1")["states"]["a"]
        self.assertEqual(due["status"],"uncertain"); self.assertEqual(due["recorded_status"],"mastered")
        for is_retest in (False,True):
            with self.assertRaises(CourseGraphError): self.diagnose(raw,is_retest=is_retest)
        self.assertEqual(self.store.load_learner("s1")["states"]["a"]["last_mastered_at"],first["learner"]["states"]["a"]["last_mastered_at"])
        passed=self.diagnose(self.evidence(text="新的独立复测"),is_retest=True)["learner"]["states"]["a"]
        self.assertEqual(passed["review_stage"],1)
        self.assertEqual(datetime.fromisoformat(passed["due_at"].replace("Z","+00:00"))-self.now,timedelta(days=7))

    def test_late_review_does_not_move_actual_mastery_evidence_time(self):
        self.publish(); raw=self.evidence(); self.now+=timedelta(days=2)
        state=self.diagnose(raw)["learner"]["states"]["a"]
        self.assertEqual(state["last_mastered_at"],raw["evidence"]["created_at"])
        self.assertTrue(state["due"])

    def test_mastered_branch_pruning_preserves_independent_parent(self):
        graph=copy.deepcopy(self.graph); graph["edges"].append(dict(graph["edges"][0],id="bd",source="b",target="d")); self.publish(graph)
        self.diagnose(self.evidence("c")); path=self.store.learning_path("d","s1")
        self.assertEqual([s["node_id"] for s in path["steps"]],["b","d"])
        self.diagnose(self.evidence("b")); self.assertTrue(self.store.learning_path("d","s1")["ready"])
        self.assertEqual(self.store.load_learner("s1")["states"]["a"]["status"],"unknown")
        self.diagnose(self.evidence("d")); self.assertEqual(len(self.store.learning_path("d","s1")["steps"]),1)

    def test_changed_node_version_rechecks_old_diagnosis_and_preserves_history(self):
        graph=self.publish(); self.diagnose(self.evidence()); graph["nodes"][0]["description"]="新概念边界"; self.now+=timedelta(minutes=1); self.publish(graph)
        state=self.store.load_learner("s1")["states"]["a"]
        self.assertTrue(state["version_changed"]); self.assertEqual(state["status"],"uncertain")
        self.assertEqual(self.store.load_learner("s1")["evidence"][0]["course_version"],2)
        self.assertEqual(self.store.load_graph("published",2)["nodes"][0]["description"],"概念说明")

    def test_reused_node_id_does_not_inherit_old_mastery(self):
        original=self.publish(); self.diagnose(self.evidence())
        removed=copy.deepcopy(original)
        removed["nodes"]=[n for n in removed["nodes"] if n["id"]!="a"]
        removed["edges"]=[e for e in removed["edges"] if "a" not in (e["source"],e["target"])]
        removed["resources"]=[]
        self.publish(removed)
        original["version"]=self.store.load_graph("draft")["version"]
        self.publish(original)
        state=self.store.load_learner("s1")["states"]["a"]
        self.assertTrue(state["version_changed"]); self.assertEqual(state["status"],"uncertain")
        self.assertEqual(state["recorded_status"],"mastered")
        verified=self.diagnose(self.evidence(text="重新加入节点后的独立核验"))["learner"]["states"]["a"]
        self.assertFalse(verified["version_changed"]); self.assertEqual(verified["status"],"mastered")

    def test_profile_interest_and_recovery_do_not_change_knowledge(self):
        self.publish(); self.diagnose(self.evidence()); before=self.store.load_learner("s1")["states"]
        self.store.save_profile({"student_id":"s1","interests":["科幻"],"background":"入门","goals":"理解分类","current_position":{"course_id":"ml_classification","course_version":2,"chapter_id":"ch1","node_id":"a","context_ref":"turn-2"}})
        reopened=CourseGraphStore(self.seed,self.store.output_dir,clock=lambda:self.now).load_learner("s1")
        self.assertEqual(reopened["states"],before); self.assertEqual(reopened["profile"]["current_position"]["context_ref"],"turn-2")
        self.assertEqual(reopened["profile"]["ability_evidence"],[]); self.assertEqual(reopened["profile"]["emotional_clues"],[])

    def test_records_are_separate_and_partial_transaction_is_invisible(self):
        self.publish(); self.diagnose(self.evidence()); folder=self.store._learner_dir("s1"); before=(folder/"HEAD.json").read_bytes()
        revision=folder/"revisions"/json.loads(before)["revision"]
        self.assertEqual({p.name for p in revision.iterdir()},{"profile.json","evidence.json","diagnoses.json","actions.json","resource_uses.json"})
        from learning_agent import course_graph as module
        original=module._atomic_json
        def fail(path,data):
            if path.name=="HEAD.json": raise OSError("synthetic failure")
            return original(path,data)
        with patch.object(module,"_atomic_json",side_effect=fail):
            with self.assertRaises(OSError): self.evidence()
        self.assertEqual((folder/"HEAD.json").read_bytes(),before); self.assertEqual(len(self.store.load_learner("s1")["evidence"]),1)

    def test_recommendation_is_idempotent_and_respects_resource_prerequisites(self):
        graph=copy.deepcopy(self.graph); graph["resources"].append(dict(graph["resources"][0],id="r_d",node_ids=["d"],prerequisite_ids=["a"]))
        self.publish(graph); first=self.store.recommendations("d","s1"); second=self.store.recommendations("d","s1")
        self.assertEqual(first["learner_version"],second["learner_version"]); self.assertEqual(len(second["learner"]["actions"]),1)
        self.assertEqual([r["id"] for r in second["resources"]],["r_a"]); self.assertEqual(second["resources"][0]["recommendation_node_id"],"a")
        result=self.store.record_resource_use({"student_id":"s1","node_id":"a","resource_id":"r_a","course_version":2})
        self.assertEqual(result["learner"]["states"]["a"]["status"],"unknown")
        preview=self.store.recommendations("d","s1","draft"); self.assertEqual(preview["learner"]["student_id"],"")

    def test_stale_versions_and_case_sensitive_student_ids(self):
        self.publish(); self.evidence(expected_version=0)
        with self.assertRaises(CourseGraphError) as error: self.evidence(expected_version=0)
        self.assertEqual(error.exception.status_code,409)
        self.evidence(student_id="S1"); self.assertNotEqual(self.store._learner_dir("s1"),self.store._learner_dir("S1"))

    def test_two_store_instances_do_not_drop_concurrent_updates(self):
        self.publish(); other=CourseGraphStore(self.seed,self.store.output_dir,clock=lambda:self.now)
        data={"student_id":"s1","node_id":"a","course_version":2,"source_type":"manual","origin":"learner_expression","prompt_level":0,"text":"原话","context":{}}
        with ThreadPoolExecutor(max_workers=2) as pool: result=list(pool.map(lambda store:store.add_evidence(data),[self.store,other]))
        self.assertEqual(sorted(r["learner"]["version"] for r in result),[1,2]); self.assertEqual(len(self.store.load_learner("s1")["evidence"]),2)

    def test_api_contract_errors_and_teacher_export(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from learning_agent import api
        app=FastAPI(); app.include_router(api.router)
        with patch.object(api,"store",self.store), TestClient(app) as client:
            self.assertIsNone(client.get("/api/course-graph").json()["graph"])
            self.assertEqual(client.get("/api/course-graph/path").status_code,422)
            self.assertIn("请求参数",client.get("/api/course-graph/path").json()["detail"])
            self.assertEqual(client.put("/api/course-graph",content="bad").status_code,400)
            graph=copy.deepcopy(self.graph); graph["nodes"][0]["expected_answer"]="答案"; self.publish(graph)
            self.assertNotIn("expected_answer",client.get("/api/course-graph/export").json()["nodes"][0])
            self.assertEqual(client.get("/api/course-graph/teacher/export").json()["nodes"][0]["expected_answer"],"答案")

    def test_optional_extraction_grounding_no_writes_and_missing_config(self):
        from learning_agent.llm import extract_candidates,load_model_config
        with self.assertRaises(CourseGraphError) as error: load_model_config(self.base/"missing.json")
        self.assertEqual(error.exception.status_code,503)
        output={"nodes":[{"id":"a","title":"A","description":"","evidence":"先学 A"},{"id":"b","title":"B","description":"","evidence":"不存在"}],"edges":[]}
        with patch("learning_agent.llm.load_model_config",return_value={}),patch("learning_agent.llm.call_llm_json",return_value=json.dumps(output)):
            result=extract_candidates({"text":"先学 A，再学 B","source_title":"测试材料"})
        self.assertEqual([n["id"] for n in result["nodes"]],["a"]); self.assertFalse(result["saved"]); self.assertTrue(result["warnings"])
        self.assertFalse(self.store.output_dir.exists())


if __name__=="__main__": unittest.main(verbosity=2)
