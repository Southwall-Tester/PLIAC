"""Synthetic command failures; no real student records or mastery claims."""
import copy
import json
import unittest

import test_linux_lab as fixtures
from pliac.linux_diagnosis import diagnose


class OperationCasesTests(unittest.TestCase):
    setUp = fixtures.LinuxLabTests.setUp
    create = fixtures.LinuxLabTests.create
    sync = fixtures.LinuxLabTests.sync
    publish = fixtures.LinuxLabTests.publish

    def prepare(self, published=False):
        if published:
            self.publish()
        self.create('published' if published else 'preview')
        self.report['events'] = self.report['events'][:1]
        self.report['operations'][0].update(exit_code=1, flags=[])
        self.report['reference_lookups'] = [dict(sequence=1, phase=2, at='2026-10-10T00:00:40Z',
                                               source='notes', topic='cp', operation_cursor=1, after_completion=False)]
        self.report['reference_total'] = 1

    def succeed(self):
        self.report['operations'].append(dict(self.report['operations'][0], sequence=2,
                                              at='2026-10-10T00:00:50Z', flags=['-a'], exit_code=0))
        self.report['operation_total'] = 2
        self.report['events'].append(dict(id=2, phase=2, kind='passed', at='2026-10-10T00:01:00Z',
                                          operation_cursor=2, prompt_level=0))
        self.report['phases_passed'] = 2

    def cases(self):
        graph = json.loads((self.folder / 'graph.json').read_text(encoding='utf-8'))
        return diagnose(self.report, self.lab.activity(graph), fixtures.DESCRIPTOR['issues'], graph)['cases']

    def test_failure_reference_success_pass_persisted_replay_and_idempotence(self):
        self.prepare(published=True)
        self.succeed()
        result = self.sync()
        case, = result['summary']['diagnosis']['cases']
        self.assertEqual(case['id'], 'operation-1')
        self.assertEqual(case['outcome'], 'operation_corrected')
        self.assertEqual(set(case['evidence_refs']), {'operation:1', 'operation:2', 'reference:1', 'check:2'})
        self.assertIn('cp', case['node_ids'])
        self.assertTrue(case['quality']['traceable'])
        self.assertFalse(case['quality']['eligible_for_mastery'])
        self.assertEqual(case['check_attempts'], 0)
        self.assertEqual(case['command_attempts'], 2)
        learner = self.store.load_learner(self.student)
        self.assertTrue(learner['diagnoses'])
        self.assertTrue(all(d['status'] == 'uncertain' for d in learner['diagnoses']))
        self.assertNotIn('mastered', {s['status'] for s in learner['states'].values()})
        replay = self.lab.sync(self.binding['binding_id'], self.student, persisted=True)
        self.assertEqual(replay['summary']['newly_imported_evidence'], 0)
        self.assertEqual(self.store.load_learner(self.student)['version'], learner['version'])
        self.assertEqual(replay['summary']['raw_digest'], result['summary']['raw_digest'])

    def test_repeated_failure_one_stable_episode_and_help_without_followup(self):
        self.prepare()
        before, = self.cases()
        self.assertIn('reference:1', before['evidence_refs'])
        self.report['operations'].append(dict(self.report['operations'][0], sequence=2))
        self.report['operation_total'] = 2
        after, = self.cases()
        self.assertEqual(after['id'], before['id'])
        self.assertEqual(after['episodes'], 1)
        self.assertEqual(after['failed_operations'], 2)
        self.assertEqual(after['outcome'], 'awaiting_verification')

    def test_refresh_replays_old_diagnosis_even_when_assessment_policy_is_current(self):
        from refresh_linux_assessments import refresh
        self.prepare()
        self.succeed()
        self.sync()
        path = self.folder / 'import.json'
        old = json.loads(path.read_text(encoding='utf-8'))
        old['diagnosis'].update(policy_version='linuxlab-evidence-diagnosis-v2', cases=[])
        path.write_text(json.dumps(old), encoding='utf-8')
        raw = (self.folder / 'raw' / (old['raw_digest'] + '.json')).read_bytes()
        refreshed = refresh(self.store)
        self.assertEqual(refreshed['refreshed'], [self.binding['binding_id']])
        self.assertEqual(refresh(self.store)['refreshed'], [])
        current = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(len(current['diagnosis']['cases']), 1)
        self.assertEqual((self.folder / 'raw' / (old['raw_digest'] + '.json')).read_bytes(), raw)

    def test_repair_prevents_crediting_later_success(self):
        self.prepare()
        self.succeed()
        self.report['events'].insert(1, dict(id=2, phase=2, kind='repair', operation_cursor=1,
                                            prompt_level=0, at='2026-10-10T00:00:45Z'))
        self.report['events'][-1]['id'] = 3
        case, = self.cases()
        self.assertEqual(case['outcome'], 'repair_boundary')
        self.assertNotIn('operation:2', case['evidence_refs'])
        self.assertNotIn('check:3', case['evidence_refs'])

    def test_pass_without_matching_operation_or_help_success_does_not_claim_correction(self):
        self.prepare()
        self.succeed()
        original = copy.deepcopy(self.report)
        for changes in ({'operand_roles': ['other']}, {'flags': ['--help']}, {'command_kind': 'alias'},
                        {'known_options': False}, {'phase': 3}):
            self.report = copy.deepcopy(original)
            self.report['operations'][1].update(changes)
            case, = self.cases()
            self.assertEqual(case['outcome'], 'later_check_passed')
            self.assertNotIn('operation:2', case['evidence_refs'])

    def test_unknown_command_and_alias_are_not_semantic_cases(self):
        self.prepare()
        for changes in ({'command_kind': 'alias'}, {'command': 'unmapped-tool'}):
            original = copy.deepcopy(self.report)
            self.report['operations'][0].update(changes)
            self.assertEqual(self.cases(), [])
            self.report = original

    def test_truncated_record_still_describes_retained_failure(self):
        self.prepare()
        self.report['operation_total'] = 40
        case, = self.cases()
        self.assertIn('过程记录不完整', ''.join(case['observations']))

    def test_tar_failure_maps_to_tar_and_listing_is_not_extraction(self):
        self.prepare()
        self.succeed()
        for op in self.report['operations']:
            op.update(command='tar', operand_roles=['supplies', 'recovered'])
        self.report['operations'][0]['flags'] = ['-xfv']
        self.report['operations'][1]['flags'] = ['-xf', '-C']
        self.report['reference_lookups'][0]['topic'] = 'tar'
        case, = self.cases()
        self.assertEqual(case['node_ids'], ['tar'])
        self.assertEqual(case['outcome'], 'operation_corrected')
        self.report['operations'][1]['flags'] = ['-tf']
        self.assertEqual(self.cases()[0]['outcome'], 'later_check_passed')

    def test_overlapping_check_linked_not_counted_as_extra_failed_check(self):
        self.prepare()
        self.report['events'].append(dict(id=2, phase=2, kind='retry', at='2026-10-10T00:01:00Z',
                                          operation_cursor=1, prompt_level=0, issue_code='backup',
                                          concepts=['copy'], problem_id=2, repeat_checks=0))
        operation = next(c for c in self.cases() if c.get('kind') == 'operation')
        self.assertEqual(operation['linked_case_ids'], ['check-2'])
        self.assertEqual(operation['check_attempts'], 0)


if __name__ == '__main__':
    unittest.main()
