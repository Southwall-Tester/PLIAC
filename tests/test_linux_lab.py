"""Synthetic evidence tests. No real learner records or human reviews."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from fastapi.testclient import TestClient
from learning_agent import api
from learning_agent.course_graph import CourseGraphError, CourseGraphStore, _atomic_json
from learning_agent.course_catalog import resolve_course
from build_linux_course import COURSE_ID, DEST
from install_course_draft import install
from connect_linuxlab_course import connect
from pliac.linux_lab import LinuxLab
from pliac.main import app

DESCRIPTOR = json.loads((DEST / "linuxlab-contract.json").read_text(encoding="utf-8"))


def sample_report(binding):
    report = {k: binding[k] for k in ("schema", "binding_id", "course_id", "course_version", "student_id", "mode", "contract_version", "contract_hash")}
    report.update(lab_session_id="synthetic-round", phases_passed=1, completed=False, tracking_enabled=True,
                  operation_total=1, input_patterns=[], events=[
                      dict(id=1, phase=1, kind="passed", at="2026-10-10T00:00:00Z", prompt_level=0, operation_cursor=0),
                      dict(id=2, phase=2, kind="retry", at="2026-10-10T00:01:00Z", prompt_level=0, operation_cursor=1,
                           issue_code="backup", concepts=["copy", "hidden", "integrity"], problem_id=2, repeat_checks=0)],
                  operations=[dict(sequence=1, phase=2, at="2026-10-10T00:00:30Z", command="cp", command_kind="file", exit_code=0,
                                   flags=["-a"], operand_roles=["original", "backup"], known_options=True,
                                   facts={"backup_hidden_present": False, "backup_nested_present": True},
                                   plain_star_excludes_hidden=False, config_changed_since_observation=False)])
    return report


class LinuxLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.default = CourseGraphStore(output_dir=Path(self.temp.name) / "store")
        install(DEST / "course.json", self.default)
        self.store = resolve_course(self.default, COURSE_ID)
        self.lab = LinuxLab(self.store)
        self.student = "synthetic-linux-test"
        self.mock = patch.object(self.lab, "descriptor", return_value=copy.deepcopy(DESCRIPTOR))
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def publish(self):
        graph = self.store.load_graph("draft")
        for group in ("nodes", "edges", "resources"):
            for row in graph[group]:
                row.update(review_status="reviewed", reviewer="SYNTHETIC TEST FIXTURE", reviewed_at=self.store._stamp(), review_note="Only isolated contract testing; not human review.")
        saved = self.store.save_graph(graph, graph["version"])["graph"]
        self.store.publish(saved["version"], "SYNTHETIC TEST FIXTURE", "Isolated test publication")

    def create(self, mode="preview"):
        view = self.lab.view(self.student, mode)
        result = self.lab.create(dict(student_id=self.student, mode=mode, course_version=view["course"]["version"], scene="space"))
        self.binding = result["binding"]
        self.folder = self.lab.directory(self.binding["binding_id"])
        self.report = sample_report(self.binding)
        _atomic_json(self.folder / "telemetry.json", self.report)
        return result

    def sync(self):
        _atomic_json(self.folder / "telemetry.json", self.report)
        return self.lab.sync(self.binding["binding_id"], self.student)

    def test_every_lab_concept_and_stage_matches_graph_and_stable_contract(self):
        graph, mode, activity = self.lab.graph()
        self.assertEqual(mode, "preview")
        self.assertEqual(len(activity["stages"]), 9)
        self.assertEqual(activity["contract_hash"], DESCRIPTOR["contract_hash"])
        for actual, mapped in zip(DESCRIPTOR["stages"], activity["stages"]):
            self.assertEqual(actual["concepts"], mapped["concepts"])
            self.assertEqual(actual["task_id"], mapped["task_id"])
            self.assertTrue(set(mapped["node_ids"]) <= {n["id"] for n in graph["nodes"]})

    def test_additive_upgrade_keeps_existing_edits_and_is_idempotent(self):
        graph = self.store.load_graph("draft")
        new_ids = {"tail", "vim", "config_record", "log_record", "top", "file_integrity"}
        graph["nodes"] = [n for n in graph["nodes"] if n["id"] not in new_ids]
        graph["edges"] = [e for e in graph["edges"] if e["source"] not in new_ids and e["target"] not in new_ids]
        graph["sources"] = [s for s in graph["sources"] if int(s["id"].split("_")[1]) <= 38]
        graph["resources"] = [r for r in graph["resources"] if not set(r["node_ids"]) <= new_ids]
        for resource in graph["resources"]:
            resource["node_ids"] = [n for n in resource["node_ids"] if n not in new_ids]
        graph.pop("activities")
        graph["nodes"][0]["description"] += " Synthetic teacher edit preserved."
        _atomic_json(self.store.graph_path, graph)
        result = connect(self.default)
        self.assertTrue(result["changed"])
        self.assertEqual(result["version"], 2)
        saved = self.store.load_graph("draft")
        self.assertIn("preserved", saved["nodes"][0]["description"])
        self.assertEqual(len(saved["nodes"]), 46)
        self.assertFalse(connect(self.default)["changed"])
        self.assertIsNone(self.store.load_graph())

    def test_repair_is_a_causal_boundary_and_report_extra_fields_are_rejected(self):
        self.create()
        self.report["events"].insert(1, dict(id=2, phase=2, kind="repair", at="2026-10-10T00:00:50Z", prompt_level=0, operation_cursor=1))
        self.report["events"][-1].update(id=3, problem_id=3)
        case = self.sync()["summary"]["diagnosis"]["cases"][0]
        self.assertNotIn("operation:1", case["evidence_refs"])
        self.report["raw_command"] = "not permitted"
        with self.assertRaisesRegex(CourseGraphError, "白名单"):
            self.sync()

    def test_preview_diagnosis_links_observations_alternatives_and_question_without_learner(self):
        self.create()
        result = self.sync()
        case = result["summary"]["diagnosis"]["cases"][0]
        self.assertIn("cp", case["node_ids"])
        self.assertIn("operation:1", case["evidence_refs"])
        self.assertIn("嵌套", "".join(case["observations"]))
        self.assertTrue(case["hypotheses"] and case["verification_questions"])
        self.assertFalse(case["quality"]["eligible_for_mastery"])
        self.assertFalse((self.store.output_dir / "learners").exists())
        self.assertIsNone(self.store.load_graph())

    def test_formal_sync_is_idempotent_separates_raw_evidence_and_draft_diagnoses(self):
        self.publish()
        self.create("published")
        result = self.sync()
        learner = self.store.load_learner(self.student)
        version = learner["version"]
        self.assertTrue(learner["evidence"] and learner["diagnoses"])
        self.assertEqual({e["origin"] for e in learner["evidence"]}, {"system_completion"})
        self.assertEqual({d["review_status"] for d in learner["diagnoses"]}, {"draft"})
        self.assertEqual({d["status"] for d in learner["diagnoses"]}, {"uncertain"})
        self.assertNotIn("mastered", {s["status"] for s in learner["states"].values()})
        self.assertTrue((self.folder / "raw" / (result["summary"]["raw_digest"] + ".json")).exists())
        self.assertEqual(self.sync()["summary"]["newly_imported_evidence"], 0)
        self.assertEqual(self.store.load_learner(self.student)["version"], version)
        reopened = CourseGraphStore(seed_path=self.store.seed_path, output_dir=self.store.output_dir)
        self.assertEqual(reopened.load_learner(self.student)["states"], learner["states"])
        self.assertEqual(reopened.load_graph(), json.loads((self.folder / "graph.json").read_text(encoding="utf-8")))
        resumed = LinuxLab(reopened).session(self.binding["binding_id"], self.student)
        self.assertEqual(resumed["binding"], self.binding)
        self.assertEqual(resumed["summary"]["raw_digest"], result["summary"]["raw_digest"])

    def test_repeat_checks_are_one_episode_and_later_success_does_not_prove_mastery(self):
        self.create()
        self.report["events"].append(dict(self.report["events"][-1], id=3, repeat_checks=1))
        self.report["events"].append(dict(id=4, phase=2, kind="passed", at="2026-10-10T00:02:00Z", prompt_level=2, operation_cursor=1))
        self.report["phases_passed"] = 2
        cases = self.sync()["summary"]["diagnosis"]["cases"]
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["check_attempts"], 2)
        self.assertEqual(cases[0]["episodes"], 1)
        self.assertEqual(cases[0]["outcome"], "artifact_corrected")
        self.assertEqual(cases[0]["diagnosis_status"], "uncertain")

    def test_aliases_do_not_supply_command_semantics_and_missing_logs_are_unknown(self):
        self.create()
        self.report["operations"][0]["command_kind"] = "alias"
        case = self.sync()["summary"]["diagnosis"]["cases"][0]
        self.assertEqual(case["evidence_refs"], ["check:2"])
        self.report["operations"] = []
        self.report["tracking_enabled"] = False
        result = self.sync()["summary"]["diagnosis"]
        self.assertFalse(result["coverage"]["tracking_enabled"])
        self.assertTrue(result["coverage"]["truncated"])
        self.assertIn("未知", "".join(result["collection_limits"]))

    def test_mid_operation_error_maps_to_syntax_and_paths_without_check_failure(self):
        self.create()
        self.report["events"] = self.report["events"][:1]
        self.report["input_patterns"] = [dict(id="input-1", kind="path_base", command="cd", concept="paths",
                                               phase=2, phases=[2], attempts=3, episodes=1, resolved_episodes=0,
                                               active=True, at="2026-10-10T00:00:30Z", operation_cursor=1)]
        case = self.sync()["summary"]["diagnosis"]["cases"][0]
        self.assertIn("relative", case["node_ids"])
        self.assertEqual(case["check_attempts"], 3)
        self.assertEqual(case["episodes"], 1)

    def test_wrong_identity_course_version_contract_and_replayed_history_rejected(self):
        self.create()
        for key, value in (("student_id", "someone-else"), ("course_version", 99), ("contract_hash", "bad")):
            saved = self.report[key]
            self.report[key] = value
            with self.assertRaises(CourseGraphError):
                self.sync()
            self.report[key] = saved
        self.sync()
        self.report["events"][-1]["issue_code"] = "unknown"
        with self.assertRaisesRegex(CourseGraphError, "改写"):
            self.sync()

    def test_old_round_preserved_and_stays_bound_after_course_edit(self):
        self.create()
        first = self.binding["binding_id"]
        self.sync()
        graph = self.store.load_graph("draft")
        graph["nodes"][0]["description"] += " Synthetic edit."
        self.store.save_graph(graph, 1)
        self.create()
        self.assertNotEqual(first, self.binding["binding_id"])
        old = self.lab.session(first, self.student)
        self.assertEqual(old["binding"]["course_version"], 1)
        self.assertEqual(old["summary"]["phases_passed"], 1)

    def test_reflection_saved_separately_and_cannot_erase_observed_help(self):
        self.publish()
        self.create("published")
        self.report["events"][-1]["prompt_level"] = 2
        self.sync()
        payload = dict(student_id=self.student, request_id="explanation-1", case_id="check-2", node_id="cp",
                       text="Synthetic explanation: target directory already existed.", prompt_level=0)
        with self.assertRaisesRegex(CourseGraphError, "提示语境"):
            self.lab.reflect(self.binding["binding_id"], payload)
        payload["prompt_level"] = 2
        self.lab.reflect(self.binding["binding_id"], payload)
        self.lab.reflect(self.binding["binding_id"], payload)
        learner = self.store.load_learner(self.student)
        speech = [e for e in learner["evidence"] if e["origin"] == "learner_expression"]
        self.assertEqual(len(speech), 1)
        self.assertEqual(speech[0]["text"], payload["text"])
        self.assertEqual(speech[0]["prompt_level"], 2)
        self.assertEqual({d["review_status"] for d in learner["diagnoses"]}, {"draft"})

    def test_artifact_checks_cannot_be_reviewed_as_mastery_without_real_expression(self):
        self.publish()
        self.create("published")
        self.sync()
        learner = self.store.load_learner(self.student)
        e = learner["evidence"][0]
        with self.assertRaisesRegex(CourseGraphError, "不能单独支持"):
            self.store.add_diagnosis(dict(student_id=self.student, course_version=e["course_version"],
                node_id=e["node_id"], evidence_ids=[e["id"]], status="mastered", review_status="reviewed",
                reviewer="SYNTHETIC TEST", basis="Must fail: artifact alone is not mastery."))

    def test_api_draft_route_launch_scope_and_cross_site_guard(self):
        with patch.object(api, "store", self.default), patch.object(LinuxLab, "descriptor", return_value=DESCRIPTOR):
            client = TestClient(app)
            url = "/api/linux-lab?course_id=" + COURSE_ID + "&student_id=" + self.student
            self.assertEqual(client.get(url).json()["mode"], "preview")
            create_url = "/api/linux-lab/runs?course_id=" + COURSE_ID
            self.assertEqual(client.post(create_url, json={}, headers={"Origin": "https://unrelated.example"}).status_code, 403)
            self.assertEqual(client.get("/linux-lab").status_code, 200)
            result = client.post(create_url, json=dict(student_id=self.student, mode="preview", course_version=1, scene="space"))
            self.assertEqual(result.status_code, 200, result.text)
            ident = result.json()["binding"]["binding_id"]
            with patch("pliac.linux_lab.subprocess.Popen") as process:
                response = client.post(f"/api/linux-lab/runs/{ident}/launch?course_id={COURSE_ID}", json={"student_id": "wrong"})
                self.assertEqual(response.status_code, 409)
                process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
