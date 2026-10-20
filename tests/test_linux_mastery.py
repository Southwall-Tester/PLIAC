"""Synthetic end-to-end assessment tests; no real learner judgments."""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

import test_linux_lab as fixtures
from learning_agent.course_graph import CourseGraphStore
from pliac.linux_lab import LinuxLab


class LinuxMasteryTests(unittest.TestCase):
    setUp = fixtures.LinuxLabTests.setUp
    create = fixtures.LinuxLabTests.create
    sync = fixtures.LinuxLabTests.sync

    def publish(self):
        graph = self.store.load_graph("draft")
        self.store.publish(graph["version"], "SYNTHETIC", "Test personal publication", personal_use=True)

    def success(self, session=None):
        self.create("published")
        self.report["lab_session_id"] = session or self.binding["binding_id"]
        self.report["events"][-1] = dict(id=2, phase=2, kind="passed", at="2026-10-11T00:00:00Z",
                                         prompt_level=0, operation_cursor=1)
        self.report["phases_passed"] = 2
        self.report["operations"][0]["facts"] = {"backup_hidden_present": True, "backup_nested_present": False}

    def estimate(self, ident="cp"):
        return self.store.load_learner(self.student)["states"][ident]["auto_assessment"]

    def reference(self, topic='cp', source='notes', cursor=0, phase=2, after_completion=False):
        rows = self.report.setdefault('reference_lookups', [])
        rows.append(dict(sequence=len(rows)+1, phase=phase, at='2026-10-10T00:00:20Z',
                         topic=topic, source=source, operation_cursor=cursor, after_completion=after_completion))
        self.report['reference_total'] = len(rows)

    def test_reference_before_success_is_supported_and_repeated_runs_are_visible(self):
        self.publish()
        for source in ('notes', 'command_help', 'man', 'shell_help'):
            self.success()
            self.reference(source=source)
            self.sync()
            self.assertEqual(self.estimate()['level'], 'referenced')
            self.assertEqual(self.estimate('file_integrity')['level'], 'referenced')
            self.assertEqual(self.estimate()['successful_streak'], 0)
            self.assertIn('reference:1', self.estimate()['evidence'][-1]['refs'])
        usage = self.estimate()['reference_usage']
        self.assertTrue(usage['recurring'])
        self.assertEqual(usage['supported_runs'], 3)
        self.assertIn('反复查阅依赖', ''.join(self.estimate()['reasons']))
        version = self.store.load_learner(self.student)['version']
        self.sync()
        self.assertEqual(self.store.load_learner(self.student)['version'], version)
        reopened = CourseGraphStore(seed_path=self.store.seed_path, output_dir=self.store.output_dir)
        self.assertEqual(reopened.load_learner(self.student)['states']['cp']['auto_assessment'], self.estimate())
        self.success()
        self.sync()
        self.success()
        self.sync()
        self.assertEqual(self.estimate()['level'], 'proficient')

    def behavior_attempt(self, corrected=True, repeat_error=False, repeat_check=False):
        self.create('published')
        self.report['lab_session_id'] = self.binding['binding_id']
        self.reference(cursor=1)
        self.report['reference_lookups'][0]['at'] = '2026-10-10T00:01:10Z'
        if repeat_error or repeat_check:
            if repeat_error:
                self.report['operations'].append(dict(self.report['operations'][0], sequence=2,
                    at='2026-10-10T00:01:20Z'))
            self.report['events'].append(dict(self.report['events'][-1], id=3,
                at='2026-10-10T00:01:30Z', operation_cursor=len(self.report['operations']),
                problem_id=3 if repeat_error else 2, repeat_checks=0 if repeat_error else 1))
        if corrected:
            sequence = len(self.report['operations']) + 1
            self.report['operations'].append(dict(self.report['operations'][0], sequence=sequence,
                at='2026-10-10T00:02:00Z',
                facts={'backup_hidden_present': True, 'backup_nested_present': False}))
            self.report['events'].append(dict(id=self.report['events'][-1]['id']+1, phase=2,
                kind='passed', at='2026-10-10T00:02:10Z', prompt_level=0, operation_cursor=sequence))
            self.report['phases_passed'] = 2
        self.report['operation_total'] = len(self.report['operations'])

    def test_reference_sequence_and_specific_copy_facets(self):
        self.publish()
        self.behavior_attempt()
        self.sync()
        result = self.estimate()
        self.assertEqual(result['level'], 'referenced')
        behavior = result['behavior']
        self.assertEqual(behavior['sequences'][0]['status'], 'corrected_after_reference')
        self.assertTrue(behavior['sequences'][0]['failure_before'])
        self.assertFalse(behavior['sequences'][0]['failure_after'])
        self.assertEqual(behavior['followup']['status'], 'pending_independent')
        self.assertEqual(len(behavior['dimensions']), 5)
        facets = {f['id']: f for f in behavior['facets']}
        self.assertEqual(facets['copy.hidden']['status'], 'corrected')
        self.assertEqual(facets['copy.layout']['status'], 'corrected')
        self.assertEqual(facets['copy.original']['status'], 'passed')
        self.assertEqual(facets['copy.operands']['status'], 'observed')
        self.assertEqual(facets['copy.hidden']['failure_episodes'], 1)
        self.assertFalse(behavior['followup']['transfer_verified'])
        version = self.store.load_learner(self.student)['version']
        self.sync()
        self.assertEqual(self.store.load_learner(self.student)['version'], version)

    def test_same_error_after_lookup_and_unchanged_checks_are_distinct(self):
        self.publish()
        self.behavior_attempt(corrected=False, repeat_error=True)
        self.sync()
        behavior = self.estimate()['behavior']
        self.assertEqual(behavior['sequences'][0]['status'], 'same_error_after_reference')
        self.assertEqual(behavior['sequences'][0]['repeated_issue_codes'], ['backup'])
        self.assertEqual(behavior['error_patterns'][0]['episodes'], 2)
        self.assertTrue(behavior['recurring_check_errors'])
        self.assertIn('同类检查错误', self.estimate()['next_action'])
        self.behavior_attempt(corrected=False, repeat_check=True)
        self.sync()
        latest = self.estimate()['behavior']['sequences'][0]
        self.assertEqual(latest['status'], 'awaiting_attempt')
        self.assertFalse(latest['failure_after'])
        # Two genuine episodes in run 1, one in run 2; duplicate check adds none.
        self.assertEqual(self.estimate()['behavior']['error_patterns'][0]['episodes'], 3)

    def test_lookup_sequences_do_not_invent_order_or_credit_repairs(self):
        self.publish()
        self.behavior_attempt()
        self.report['reference_lookups'][0]['at'] = self.report['events'][1]['at']
        self.sync()
        self.assertEqual(self.estimate()['behavior']['sequences'][0]['status'], 'reference_then_success')
        self.assertFalse(self.estimate()['behavior']['sequences'][0]['failure_before'])
        self.behavior_attempt()
        self.report['events'].insert(2, dict(id=3, phase=2, kind='repair',
            at='2026-10-10T00:01:30Z', prompt_level=0, operation_cursor=1))
        self.report['events'][-1]['id'] = 4
        self.sync()
        self.assertEqual(self.estimate()['level'], 'insufficient')
        self.assertEqual(self.estimate()['behavior']['sequences'][0]['status'], 'uncertain')
        self.assertFalse(any(f['status'] in ('passed', 'corrected') for f in self.estimate()['behavior']['facets']))

    def test_failed_check_requires_new_successful_operation(self):
        self.publish()
        self.create('published')
        self.report['operations'][0]['facts'] = dict(backup_hidden_present=True, backup_nested_present=False)
        self.report['events'].append(dict(id=3, phase=2, kind='passed',
            at='2026-10-10T00:02:00Z', prompt_level=0, operation_cursor=1))
        self.report['phases_passed'] = 2
        self.sync()
        self.assertEqual(self.estimate()['level'], 'insufficient')
        self.assertEqual(self.estimate()['behavior']['followup']['status'], 'pending_independent')

    def test_followup_requires_distinct_run_and_actual_chronology(self):
        self.publish()
        self.behavior_attempt()
        self.sync()
        prior = self.binding['binding_id']
        self.success()
        # A later sync with earlier performance is not a follow-up.
        self.sync()
        self.assertEqual(self.estimate()['behavior']['followup']['status'], 'not_verified')
        self.success()
        for i, event in enumerate(self.report['events']):
            event['at'] = f'2026-10-12T00:0{i}:00Z'
        self.report['operations'][0]['at'] = '2026-10-12T00:00:30Z'
        self.sync()
        followup = self.estimate()['behavior']['followup']
        self.assertEqual(followup['status'], 'independent_followup')
        self.assertEqual(followup['records'][0]['prior_binding_id'], prior)
        self.assertGreater(followup['records'][0]['gap_hours'], 24)
        self.assertFalse(followup['transfer_verified'])
        self.assertIn('换任务条件', self.estimate()['next_action'])
        self.assertFalse(self.estimate()['human_reviewed'])

    def test_post_success_review_has_no_effect_on_followup_or_timestamp(self):
        self.publish()
        self.success()
        self.sync()
        before = copy.deepcopy(self.estimate())
        self.reference(cursor=1)
        self.sync()
        after = self.estimate()
        self.assertEqual(after['updated_at'], before['updated_at'])
        self.assertEqual(after['level'], before['level'])
        self.assertEqual(after['behavior']['sequences'][0]['status'], 'review_after_success')
        self.assertEqual(after['behavior']['followup']['status'], 'not_verified')

    def test_policy_upgrade_keeps_performance_timestamp_and_raw_graph(self):
        from learning_agent.course_graph import _atomic_json
        self.publish()
        self.success()
        self.sync()
        before = self.estimate()['updated_at']
        summary = json.loads((self.folder / 'import.json').read_text(encoding='utf-8'))
        raw = (self.folder / 'raw' / (summary['raw_digest'] + '.json')).read_bytes()
        summary['assessment']['policy_version'] = 'linuxlab-mastery-v2'
        summary['assessment']['nodes']['cp']['observation_key'] = 'legacy-key'
        _atomic_json(self.folder / 'import.json', summary)
        self.sync()
        self.assertEqual(self.estimate()['updated_at'], before)
        self.assertEqual(self.estimate()['policy_version'], 'linuxlab-mastery-v3')
        self.assertEqual((self.folder / 'raw' / (summary['raw_digest'] + '.json')).read_bytes(), raw)

    def test_refresh_uses_imported_raw_without_importing_unsynced_work(self):
        from learning_agent.course_graph import _atomic_json
        from refresh_linux_assessments import refresh
        self.publish()
        self.behavior_attempt(corrected=False)
        self.sync()
        saved = json.loads((self.folder / 'import.json').read_text(encoding='utf-8'))
        stamp = self.estimate()['updated_at']
        saved['assessment']['policy_version'] = 'linuxlab-mastery-v2'
        _atomic_json(self.folder / 'import.json', saved)
        # Deliberately invalid unsynced telemetry: migration must not read it.
        _atomic_json(self.folder / 'telemetry.json', {'not': 'a report'})
        result = refresh(self.store)
        self.assertEqual(result['refreshed'], [self.binding['binding_id']])
        self.assertEqual(self.estimate()['level'], 'needs_practice')
        self.assertEqual(self.estimate()['updated_at'], stamp)
        self.assertEqual(self.estimate()['policy_version'], 'linuxlab-mastery-v3')
        self.assertEqual(refresh(self.store)['refreshed'], [])

    def test_general_unrelated_and_post_operation_reference_does_not_downgrade(self):
        self.publish()
        for topic, source, cursor, phase, completed in (
            ('', 'lab_help', 0, 2, False), ('', 'notes', 0, 2, False),
            ('vim', 'notes', 0, 2, False), ('cp', 'notes', 1, 2, False),
            ('cp', 'notes', 1, 3, False), ('cp', 'notes', 1, 9, True),
        ):
            with self.subTest(topic=topic, source=source, phase=phase, cursor=cursor):
                self.success()
                self.reference(topic, source, cursor, phase, completed)
                self.sync()
                self.assertIn(self.estimate()['level'], ('developing', 'proficient'))
                self.assertEqual(self.estimate()['reference_usage']['supported_runs'], 0)

    def test_review_of_old_run_does_not_overwrite_new_difficulty(self):
        self.publish()
        self.success()
        old_binding, old_folder, old_report = self.binding, self.folder, copy.deepcopy(self.report)
        self.sync()
        old_stamp = self.estimate()['updated_at']
        self.create('published')
        self.report['lab_session_id'] = self.binding['binding_id']
        self.sync()
        self.assertEqual(self.estimate()['level'], 'needs_practice')
        self.binding, self.folder, self.report = old_binding, old_folder, old_report
        self.reference(cursor=1, phase=3)
        self.sync()
        self.assertEqual(self.estimate()['level'], 'needs_practice')
        saved = json.loads((self.folder / 'import.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['assessment']['nodes']['cp']['updated_at'], old_stamp)

    def test_reference_with_failure_help_or_repair_preserves_stronger_evidence(self):
        self.publish()
        self.create('published')
        self.reference()
        self.sync()
        self.assertEqual(self.estimate()['level'], 'needs_practice')
        for kind, expected in (('hint', 'assisted'), ('repair', 'insufficient')):
            self.success()
            self.reference()
            self.report['events'][-1]['id'] = 3
            self.report['events'].insert(1, dict(id=2, phase=2, kind=kind,
                at='2026-10-10T00:00:25Z', prompt_level=0, operation_cursor=0))
            self.sync()
            self.assertEqual(self.estimate()['level'], expected)

    def test_reference_report_validation_and_immutable_history(self):
        from learning_agent.course_graph import CourseGraphError
        self.publish()
        self.success()
        self.reference()
        self.sync()
        original = copy.deepcopy(self.report)
        for key, value in (('topic', 'private-user-text'), ('operation_cursor', 999), ('source', [])):
            self.report = copy.deepcopy(original)
            self.report['reference_lookups'][0][key] = value
            with self.assertRaises(CourseGraphError):
                self.sync()
        self.report = copy.deepcopy(original)
        self.report['reference_lookups'] = []
        with self.assertRaises(CourseGraphError):
            self.sync()
        self.report = copy.deepcopy(original)
        self.report['reference_lookups'][0]['topic'] = 'vim'
        with self.assertRaisesRegex(CourseGraphError, '改写'):
            self.sync()

    def test_progress_regression_idempotency_and_unchanged_graph(self):
        self.publish()
        path = self.store.output_dir / "published/v1.json"
        before = path.read_bytes()
        self.success()
        self.sync()
        self.assertEqual(self.estimate()["level"], "developing")
        self.assertEqual(self.estimate("absolute")["level"], "insufficient")
        self.assertEqual(self.estimate("grep")["level"], "not_observed")
        version = self.store.load_learner(self.student)["version"]
        self.sync()
        self.assertEqual(self.store.load_learner(self.student)["version"], version)
        self.assertEqual(self.estimate()["runs_observed"], 1)
        self.success()
        self.sync()
        self.assertEqual(self.estimate()["level"], "proficient")
        self.create("published")
        self.report["lab_session_id"] = self.binding["binding_id"]
        self.sync()
        self.assertEqual(self.estimate()["level"], "needs_practice")
        # A correction updates this run; it is not another independent success.
        self.report["operations"].append(dict(self.report["operations"][0], sequence=2,
            facts={"backup_hidden_present": True, "backup_nested_present": False}))
        self.report["operation_total"] = 2
        self.report["events"].append(dict(id=3, phase=2, kind="passed", at="2026-10-11T00:01:00Z",
                                          prompt_level=0, operation_cursor=2))
        self.report["phases_passed"] = 2
        self.sync()
        self.assertEqual(self.estimate()["level"], "developing")
        self.assertEqual(self.estimate()["successful_streak"], 0)
        self.assertEqual(self.estimate()["runs_observed"], 3)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.estimate()["human_reviewed"])
        self.assertNotEqual(self.store.load_learner(self.student)["states"]["cp"]["status"], "mastered")
        self.assertGreaterEqual(len(list((self.folder / "assessments").glob("*.json"))), 2)

    def test_hints_tutor_repair_and_missing_observation(self):
        self.publish()
        for kind, expected in (("hint", "assisted"), ("tutor", "assisted"), ("repair", "insufficient")):
            with self.subTest(kind=kind):
                self.success()
                self.report["events"][-1]["id"] = 3
                self.report["events"].insert(1, dict(id=2, phase=2, kind=kind,
                    at="2026-10-10T00:01:00Z", prompt_level=0, operation_cursor=0))
                self.sync()
                self.assertEqual(self.estimate()["level"], expected)
        for change in ("off", "truncated", "alias", "no_operations"):
            with self.subTest(change=change):
                self.success()
                if change == "off": self.report["tracking_enabled"] = False
                if change == "truncated": self.report["operation_total"] = 2
                if change == "alias": self.report["operations"][0]["command_kind"] = "alias"
                if change == "no_operations":
                    self.report["operations"] = []
                    self.report["operation_total"] = 0
                    self.report["events"][-1]["operation_cursor"] = 0
                self.sync()
                self.assertEqual(self.estimate()["level"], "insufficient")

    def test_replayed_save_is_not_multiple_trials_and_student_isolation(self):
        self.publish()
        for _ in range(3):
            self.success("same-native-save")
            self.sync()
        self.assertEqual(self.estimate()["runs_observed"], 1)
        self.assertEqual(self.estimate()["level"], "developing")
        other = self.store.load_learner("synthetic-other")
        self.assertNotIn("auto_assessment", other["states"]["cp"])

    def test_reopen_and_invalidate_changed_node_without_destroying_history(self):
        self.publish()
        self.success()
        self.sync()
        initial = copy.deepcopy(self.estimate())
        reopened = CourseGraphStore(seed_path=self.store.seed_path, output_dir=self.store.output_dir)
        self.assertEqual(reopened.load_learner(self.student)["states"]["cp"]["auto_assessment"], initial)
        self.assertEqual(LinuxLab(reopened).session(self.binding["binding_id"], self.student)["assessments"]["cp"], initial)
        graph = self.store.load_graph("draft")
        next(n for n in graph["nodes"] if n["id"] == "cp")["description"] += " New synthetic scope."
        self.store.save_graph(graph, graph["version"])
        self.publish()
        self.assertEqual(self.estimate()["level"], "insufficient")
        self.assertEqual(self.estimate()["excluded_version_records"], 1)
        frozen = json.loads((self.folder / "graph.json").read_text(encoding="utf-8"))
        self.assertEqual(self.store.load_learner(self.student, frozen)["states"]["cp"]["auto_assessment"], initial)

    def test_preview_does_not_write_learner_estimates(self):
        self.create("preview")
        result = self.sync()
        self.assertTrue(result["summary"]["assessment"]["nodes"])
        self.assertEqual(result["assessments"], {})
        self.assertFalse((self.store.output_dir / "learners").exists())

    def test_other_phase_sync_cannot_promote_old_success_over_new_failure(self):
        self.publish()
        self.success()
        self.sync()
        previous = self.binding, self.folder, copy.deepcopy(self.report)
        previous_time = self.estimate()["updated_at"]
        self.create("published")
        self.report["lab_session_id"] = self.binding["binding_id"]
        self.sync()
        self.assertEqual(self.estimate()["level"], "needs_practice")
        self.binding, self.folder, self.report = previous
        self.report["events"].append(dict(id=3, phase=3, kind="hint", at="2026-10-11T00:01:00Z",
                                          prompt_level=1, operation_cursor=1))
        self.sync()
        self.assertEqual(self.estimate()["level"], "needs_practice")
        old = self.store.load_learner(self.student)["workspace"]["linuxlab"][self.binding["binding_id"]]["assessment"]
        self.assertEqual(old["nodes"]["cp"]["updated_at"], previous_time)

    def timed_success(self, seconds):
        self.success()
        start = datetime(2026, 10, 11, tzinfo=timezone.utc)
        self.report["events"][0]["at"] = start.isoformat()
        self.report["operations"][0]["at"] = (start + timedelta(seconds=min(30, seconds / 2))).isoformat()
        self.report["events"][-1]["at"] = (start + timedelta(seconds=seconds)).isoformat()

    def typo(self, episodes=1, attempts=1, active=False):
        self.report["input_patterns"] = [dict(id="synthetic-typo", kind="command_typo", command="cp",
            concept="copy", phase=2, phases=[2], attempts=attempts, episodes=episodes,
            resolved_episodes=0 if active else episodes, active=active,
            at=self.report["events"][-1]["at"], operation_cursor=self.report["operation_total"])]

    def test_single_slip_repeated_typos_and_corrected_checks(self):
        self.publish()
        self.success()
        self.sync()
        self.success()
        self.typo(episodes=1, attempts=20)
        self.sync()
        self.assertEqual(self.estimate()["fluency"]["status"], "isolated_slip")
        self.assertEqual(self.estimate()["level"], "proficient")
        self.success()
        self.typo(episodes=2, attempts=3)
        self.sync()
        self.assertEqual(self.estimate()["fluency"]["status"], "recurring_errors")
        self.assertEqual(self.estimate()["level"], "developing")
        self.success()
        self.typo(episodes=2, attempts=2, active=True)
        self.sync()
        self.assertEqual(self.estimate()["level"], "needs_practice")
        self.assertEqual(self.estimate()["fluency"]["unresolved_episodes"], 2)

    def test_timing_uses_personal_baseline_and_never_penalizes_pause_alone(self):
        self.publish()
        for _ in range(3):
            self.timed_success(20)
            self.sync()
        self.timed_success(60)
        self.sync()
        timing = next(t for t in self.estimate()["timing"] if t["phase"] == 2)
        self.assertEqual(timing["comparison"], "slower")
        self.assertEqual(timing["baseline_samples"], 3)
        self.assertEqual(timing["baseline_seconds"], 20)
        self.assertEqual(self.estimate()["level"], "proficient")
        self.timed_success(60)
        self.typo(episodes=2, attempts=3)
        self.sync()
        timing = next(t for t in self.estimate()["timing"] if t["phase"] == 2)
        self.assertEqual(timing["comparison"], "slower_with_difficulty")
        self.timed_success(600)
        self.sync()
        timing = next(t for t in self.estimate()["timing"] if t["phase"] == 2)
        self.assertEqual(timing["comparison"], "interrupted")
        self.assertEqual(timing["unobserved_seconds"], 570)
        self.assertEqual(timing["continuous_seconds"], 30)


if __name__ == "__main__":
    unittest.main()
