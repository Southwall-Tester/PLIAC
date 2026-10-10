import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import patch
from types import SimpleNamespace
import json

from learning_agent.acceptance_course import AcceptanceCourseStore
from learning_agent.course_graph import CourseGraphStore
from pliac.tutor import TeachingProposal
from pliac.tutor_quality import CASES, case_context, evaluate_cases


class QualityTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = AcceptanceCourseStore(CourseGraphStore(output_dir=Path(folder.name)))

    def test_all_cases_use_real_course_context_and_distinct_foundations(self):
        contexts = [case_context(self.store, case) for case in CASES]
        for case, context in zip(CASES, contexts):
            self.assertIn(case['node'], {node['id'] for node in context['nodes']})
            self.assertTrue(context['sources'])
        self.assertNotEqual(contexts[1], contexts[2])
        self.assertEqual(CASES[1]['message'], CASES[2]['message'])

    def test_valid_structure_never_implies_semantic_pass(self):
        proposal = TeachingProposal(response='合成测试响应', target_node_id='sample', action='probe',
            rationale='工程测试', blocks=[], question='请解释', uncertainty='尚未进行教学质量评审')
        model = AsyncMock(return_value=(proposal, {'model': 'synthetic', 'api_key': 'DO_NOT_EXPORT'}))
        report = asyncio.run(evaluate_cases(self.store, [CASES[0]], model, None))
        self.assertEqual(report['results'][0]['structure_status'], 'passed')
        self.assertEqual(report['semantic_status'], 'not_reviewed')
        self.assertFalse(report['live_model'])
        self.assertNotIn('DO_NOT_EXPORT', str(report))
        self.assertEqual(model.await_count, 1)

    def test_failure_keeps_later_cases_and_does_not_export_raw_errors(self):
        model = AsyncMock(side_effect=RuntimeError('secret-provider-key'))
        report = asyncio.run(evaluate_cases(self.store, CASES[:2], model, None))
        self.assertEqual(len(report['results']), 2)
        self.assertTrue(all(row['structure_status'] == 'failed' for row in report['results']))
        self.assertNotIn('secret-provider-key', str(report))
        self.assertEqual(model.await_count, 2)

    def test_source_attack_remains_data_and_does_not_modify_course(self):
        from pliac.tutor import generate_teaching
        case = next(case for case in CASES if case['id'] == 'source-injection')
        before = self.store.load_graph()
        context = case_context(self.store, case)
        self.assertNotIn('SYSTEM OVERRIDE', context['message'])
        self.assertIn('SYSTEM OVERRIDE', context['sources'][0]['text'])
        self.assertEqual(before, self.store.load_graph())
        proposal = TeachingProposal(response='仅解释课程概念', target_node_id='sample', action='probe',
            rationale='合成测试', blocks=[], question='请举例', uncertainty='待核验')
        with patch('pliac.tutor.Provider') as factory:
            provider = factory.return_value.__aenter__.return_value
            provider.generate = AsyncMock(return_value=proposal)
            provider.usage = []
            asyncio.run(generate_teaching(context, SimpleNamespace(model='synthetic', api_key='SECRET_CANARY')))
            schema, system, data = provider.generate.call_args.args
        self.assertIs(schema, TeachingProposal)
        self.assertNotIn('SYSTEM OVERRIDE', system)
        self.assertIn('不能覆盖本规则', system)
        self.assertIn('SYSTEM OVERRIDE', json.loads(data)['sources'][0]['text'])
        self.assertNotIn('SECRET_CANARY', system + data)

    def test_attack_cannot_add_privileged_output_fields(self):
        from pydantic import ValidationError
        from pliac.tutor import check_teaching
        from learning_agent.course_graph import CourseGraphError
        case = next(case for case in CASES if case['id'] == 'source-injection')
        context = case_context(self.store, case)
        fields = dict(response='Synthetic', target_node_id='sample', action='probe',
                      rationale='Synthetic', blocks=[], question='', uncertainty='')
        for extra in ({'mastered': True}, {'tool_calls': [{'name': 'publish'}]}, {'student_id': 'another-student'}, {'action': 'publish'}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                TeachingProposal.model_validate(fields | extra)
        with self.assertRaises(CourseGraphError):
            check_teaching(TeachingProposal.model_validate(fields | {'target_node_id': 'foreign-private-node'}), context)
