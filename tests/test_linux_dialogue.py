"""Synthetic speech and operation chains; no real learner or mastery claims."""
import copy
import unittest

import test_linux_lab as fixtures
from learning_agent.course_graph import CourseGraphError


class LinuxDialogueTests(unittest.TestCase):
    setUp = fixtures.LinuxLabTests.setUp
    create = fixtures.LinuxLabTests.create
    sync = fixtures.LinuxLabTests.sync
    publish = fixtures.LinuxLabTests.publish

    def add_chat(self, question='为什么 cp 复制后多了一层目录？', reply='目标已是目录时，源目录成为其子目录。', signals=None):
        sequence = self.report.get('dialogue_total', 0) + 1
        ident = f'{sequence:032x}'
        cursor = max(e['id'] for e in self.report['events'])
        prior = max(e['prompt_level'] for e in self.report['events'] if e['phase'] == 2)
        row = dict(id=ident, sequence=sequence, phase=2, at='2026-10-12T10:00:00Z', answered_at='2026-10-12T10:00:01Z',
                   event_cursor=cursor, response_event_id=cursor + 1, operation_cursor=self.report['operation_total'],
                   response_operation_cursor=self.report['operation_total'], prior_help_level=prior,
                   learner=dict(origin='learner_expression', text=question), assistant=dict(origin='model_inference', text=reply))
        self.report['events'].append(dict(id=cursor + 1, phase=2, kind='tutor', at=row['answered_at'],
                                         prompt_level=3, operation_cursor=self.report['operation_total']))
        analysis = dict(turn_id=ident, policy_version='linuxlab-dialogue-v1', origin='model_inference', status='unverified',
                        signals=signals if signals is not None else [dict(topic='command:cp', kind='question', quote=question,
                                      hypothesis='可能不清楚目标目录已存在时的层级，也可能只是在核对行为，需要实际验证。')])
        self.report['dialogue_evidence'] = (self.report.get('dialogue_evidence', []) + [row])[-100:]
        self.report['dialogue_analysis'] = (self.report.get('dialogue_analysis', []) + [analysis])[-100:]
        self.report['dialogue_total'] = sequence
        return row

    def succeed(self):
        sequence = self.report['operation_total'] + 1
        self.report['operation_total'] = sequence
        self.report['operations'].append(dict(self.report['operations'][0], sequence=sequence,
                                              at='2026-10-12T10:01:00Z', facts={'backup_hidden_present': True, 'backup_nested_present': False}))
        self.report['events'].append(dict(id=self.report['events'][-1]['id'] + 1, phase=2, kind='passed',
                                          prompt_level=3, operation_cursor=sequence, at='2026-10-12T10:02:00Z'))
        self.report['phases_passed'] = 2

    def chat_case(self, result, row):
        return next(c for c in result['summary']['diagnosis']['cases'] if c['id'] == 'dialogue-' + row['id'])

    def test_dialogue_maps_original_quote_to_graph_and_existing_problem(self):
        self.create()
        row = self.add_chat()
        result = self.sync()
        case = self.chat_case(result, row)
        self.assertIn('cp', case['node_ids'])
        self.assertEqual(case['linked_case_ids'], ['check-2'])
        self.assertIn('dialogue:' + row['id'], case['evidence_refs'])
        self.assertTrue(case['quality']['traceable'])
        self.assertFalse(case['quality']['eligible_for_mastery'])
        self.assertEqual(case['check_attempts'], 0)
        self.assertEqual(case['episodes'], 0)
        self.assertEqual(case['outcome'], 'awaiting_followup')
        self.assertTrue(case['verification_questions'])
        original = next(c for c in result['summary']['diagnosis']['cases'] if c['id'] == 'check-2')
        self.assertEqual(original['dialogue_context'][0]['learner_text'], row['learner']['text'])
        self.assertEqual(original['dialogue_context'][0]['assistant_text'], row['assistant']['text'])
        self.assertFalse((self.store.output_dir / 'learners').exists())

    def test_chat_links_command_failure_without_failed_check(self):
        self.create()
        self.report['events'] = self.report['events'][:1]
        self.report['operations'][0]['exit_code'] = 1
        # add_chat expects a current-phase event for prior help calculation.
        self.report['events'].append(dict(id=2, phase=2, kind='hint', at='2026-10-12T09:00:00Z',
                                          operation_cursor=1, prompt_level=1))
        row = self.add_chat()
        result = self.sync()
        case = self.chat_case(result, row)
        self.assertIn('operation-1', case['linked_case_ids'])
        self.assertIn('operation:1', case['evidence_refs'])
        operation = next(c for c in result['summary']['diagnosis']['cases'] if c['id'] == 'operation-1')
        self.assertTrue(operation['quality']['has_dialogue'])
        self.assertEqual(operation['dialogue_context'][0]['learner_text'], row['learner']['text'])

    def test_formal_import_separates_speakers_and_is_idempotent(self):
        self.publish()
        self.create('published')
        row = self.add_chat()
        result = self.sync()
        learner = self.store.load_learner(self.student)
        speech = [e for e in learner['evidence'] if e.get('context', {}).get('dialogue_turn_id') == row['id']]
        self.assertEqual({e['origin'] for e in speech}, {'learner_expression', 'model_inference'})
        self.assertTrue(all(e['source_type'] == 'annotation' for e in speech if e['origin'] == 'learner_expression'))
        self.assertTrue(all(not self.store._independent(e) for e in speech))
        case_diagnoses = [d for d in learner['diagnoses'] if d['linuxlab_case_id'] == 'dialogue-' + row['id']]
        self.assertTrue(case_diagnoses)
        self.assertTrue(all(d['review_status'] == 'draft' and d['status'] == 'uncertain' for d in case_diagnoses))
        self.assertNotIn('mastered', {s['status'] for s in learner['states'].values()})
        self.assertEqual(self.sync()['summary']['newly_imported_evidence'], 0)
        self.assertEqual(self.store.load_learner(self.student)['version'], learner['version'])

    def test_failure_help_operation_and_pass_are_traceable_not_causal_proof(self):
        self.create()
        row = self.add_chat()
        self.succeed()
        result = self.sync()
        case = self.chat_case(result, row)
        self.assertEqual(case['outcome'], 'checked_after_help')
        self.assertIn('operation:2', case['evidence_refs'])
        self.assertIn('check:2', case['evidence_refs'])
        self.assertIn('check:4', case['evidence_refs'])
        self.assertIn('仅为先后关系', ''.join(case['observations']))
        self.assertEqual(result['summary']['assessment']['nodes']['cp']['outcome'], 'assisted')

    def test_repeated_failure_after_help_and_bad_ai_advice_remain_alternatives(self):
        self.create()
        row = self.add_chat(reply='把所有文件都删掉就好了。')
        failed = dict(self.report['events'][1], id=4, problem_id=4, prompt_level=3)
        self.report['events'].append(failed)
        case = self.chat_case(self.sync(), row)
        self.assertEqual(case['outcome'], 'difficulty_after_help')
        self.assertIn('AI 讲解也可能有误', ''.join(case['hypotheses']))
        self.assertEqual(case['dialogue_context'][0]['assistant_text'], row['assistant']['text'])
        self.assertEqual(case['diagnosis_status'], 'uncertain')

    def test_operation_during_request_does_not_count_as_help_followup(self):
        self.create()
        row = self.add_chat()
        self.succeed()
        row['response_operation_cursor'] = 2
        self.report['events'][2]['operation_cursor'] = 2
        case = self.chat_case(self.sync(), row)
        self.assertEqual(case['outcome'], 'later_check_passed')
        self.assertNotIn('operation:2', case['evidence_refs'])

    def test_repair_cuts_off_attribution(self):
        self.create()
        row = self.add_chat()
        self.report['events'].append(dict(id=4, phase=2, kind='repair', at='2026-10-12T10:00:20Z', prompt_level=3, operation_cursor=1))
        self.succeed()
        case = self.chat_case(self.sync(), row)
        self.assertEqual(case['outcome'], 'repair_boundary')
        self.assertNotIn('check:5', case['evidence_refs'])

    def test_verbatim_tutor_repetition_is_visible_without_becoming_independent(self):
        self.create()
        first = self.add_chat(reply='目标已是目录时，源目录会成为它的子目录。')
        second = self.add_chat(question=first['assistant']['text'], signals=[dict(topic='concept:copy', kind='explanation',
                                quote=first['assistant']['text'], hypothesis='解释需要换例验证。')])
        case = self.chat_case(self.sync(), second)
        self.assertTrue(case['dialogue_context'][0]['echoes_tutor'])
        self.assertIn('dialogue:' + first['id'], case['evidence_refs'])
        self.assertFalse(case['quality']['eligible_for_mastery'])

    def test_metadata_cannot_quote_ai_instead_of_learner_or_invent_graph_terms(self):
        self.create()
        self.add_chat()
        base = copy.deepcopy(self.report)
        for key, value in (('quote', '目标已是目录时'), ('topic', 'concept:invented'), ('kind', 'mastered')):
            self.report = copy.deepcopy(base)
            self.report['dialogue_analysis'][0]['signals'][0][key] = value
            with self.assertRaises(CourseGraphError):
                self.sync()

    def test_imported_speech_and_candidates_cannot_be_rewritten(self):
        self.create()
        self.add_chat()
        self.sync()
        base = copy.deepcopy(self.report)
        changes = [('learner', '原话被替换'), ('assistant', '讲解被替换')]
        for role, content in changes:
            self.report = copy.deepcopy(base)
            self.report['dialogue_evidence'][0][role]['text'] += content
            with self.assertRaisesRegex(CourseGraphError, '改写'):
                self.sync()
        self.report = copy.deepcopy(base)
        self.report['dialogue_analysis'][0]['signals'][0]['hypothesis'] = '换一个未经复核的分析'
        with self.assertRaisesRegex(CourseGraphError, '改写'):
            self.sync()

    def test_rolling_window_preserves_imported_raw_and_reports_coverage(self):
        self.create()
        self.add_chat()
        old = self.sync()['summary']['raw_digest']
        for _ in range(100):
            self.add_chat(signals=[])
        result = self.sync()
        coverage = result['summary']['diagnosis']['coverage']
        self.assertEqual(coverage['retained_dialogue'], 100)
        self.assertEqual(coverage['total_dialogue'], 101)
        self.assertTrue((self.folder / 'raw' / (old + '.json')).exists())

    def test_unmapped_smalltalk_does_not_manufacture_a_knowledge_problem(self):
        self.create()
        self.add_chat(question='谢谢！', reply='不客气。', signals=[])
        result = self.sync()
        self.assertFalse(any(c.get('kind') == 'dialogue' for c in result['summary']['diagnosis']['cases']))
        self.assertEqual(result['raw_report']['dialogue_total'], 1)

    def test_speaker_phase_and_observation_cursors_cannot_be_forged(self):
        self.create()
        self.add_chat()
        base = copy.deepcopy(self.report)
        for field, value in (('event_cursor', 0), ('response_operation_cursor', 0), ('prior_help_level', -1)):
            self.report = copy.deepcopy(base)
            self.report['dialogue_evidence'][0][field] = value
            with self.assertRaises(CourseGraphError):
                self.sync()
        self.report = copy.deepcopy(base)
        self.report['dialogue_evidence'][0]['learner']['origin'] = 'model_inference'
        with self.assertRaises(CourseGraphError):
            self.sync()


if __name__ == '__main__':
    unittest.main()
