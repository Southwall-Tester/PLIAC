import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learning_agent.course_graph import CourseGraphError
from pliac.tutor import AssessmentProposal, TeachingProposal, assess_evidence, check_teaching


class TutorContracts(unittest.TestCase):
    def proposal(self):
        return TeachingProposal(response="先比较训练与验证。", target_node_id="split", action="explain", rationale="先核验数据用途。",
            blocks=[{"heading": "数据用途", "text": "验证集用于比较模型。", "citations": [{"source_id": "s1", "quote": "验证集用于比较模型"}]}],
            question="为什么不能用测试集选择模型？", uncertainty="尚未核验学生理解")

    def test_source_and_scope_are_checked(self):
        context = {"nodes": [{"id": "split"}], "sources": [{"id": "s1", "text": "验证集用于比较模型。"}], "lab_available": False}
        check_teaching(self.proposal(), context)
        for change in [{"target_node_id": "other"}, {"action": "lab"}]:
            with self.assertRaises(CourseGraphError):
                check_teaching(self.proposal().model_copy(update=change), context)
        altered = self.proposal()
        altered.blocks[0].citations[0].quote = "测试集可以反复选模型"
        with self.assertRaises(CourseGraphError):
            check_teaching(altered, context)

    def test_fixed_rubric_and_independent_evidence(self):
        result = AssessmentProposal(criteria=[{"criterion_id": "purpose", "outcome": "met", "quote": "验证集选模型", "reason": "说明用途"}], feedback="用途解释正确。", follow_up_question="")
        args = dict(rubric=[{"id": "purpose", "text": "解释验证集用途"}], answer="我用验证集选模型。", assistance_level=0, exposed=False, independent_task=True)
        self.assertEqual(assess_evidence(result, **args)["status"], "mastery_supported")
        for altered in [{"assistance_level": 1}, {"exposed": True}, {"independent_task": False}]:
            self.assertEqual(assess_evidence(result, **(args | altered))["status"], "assisted_success")
        with self.assertRaises(CourseGraphError):
            assess_evidence(result, **(args | {"answer": "不知道"}))
        with self.assertRaises(CourseGraphError):
            assess_evidence(result, **(args | {"rubric": [{"id": "other"}]}))

    def test_resource_catalog_is_bounded_and_recommendations_match_target(self):
        from pliac.tutor import teaching_context, ResourceRecommendation
        from test_learning_workspace import platform_fixture
        graph = platform_fixture()
        template = graph['resources'][0]
        graph['resources'] = [{**template, 'id': f'r{index}', 'review_status': 'auto_validated'} for index in range(30)]
        graph['resources'].insert(0, {**template, 'id': 'draft', 'review_status': 'draft'})
        graph['resources'].insert(0, {**template, 'id': 'no-link', 'url': '', 'review_status': 'reviewed'})
        context = teaching_context(graph, {'version': 0, 'profile': {}, 'states': {}}, 'a', '合成问题')
        self.assertEqual(len(context['resources']), 24)
        self.assertTrue(context['resources_truncated'])
        self.assertFalse({'draft', 'no-link'} & {item['id'] for item in context['resources']})
        proposal = self.proposal()
        proposal.target_node_id = 'a'; proposal.blocks = []
        proposal.recommended_resources = [ResourceRecommendation(resource_id='r0', reason='相关资料')]
        check_teaching(proposal, context)
        for change in ('duplicate', 'wrong-target', 'missing'):
            with self.subTest(change=change):
                candidate = proposal.model_copy(deep=True)
                if change == 'duplicate':
                    candidate.recommended_resources.append(candidate.recommended_resources[0])
                elif change == 'wrong-target':
                    candidate.target_node_id = 'c'
                else:
                    candidate.recommended_resources[0].resource_id = 'missing'
                with self.assertRaises(CourseGraphError):
                    check_teaching(candidate, context)

    def test_incomplete_and_duplicate_criteria_cannot_pass(self):
        result = AssessmentProposal(criteria=[{"criterion_id": "purpose", "outcome": "insufficient", "quote": "", "reason": "没有解释"}], feedback="还需要解释。", follow_up_question="为什么？")
        args = dict(rubric=[{"id": "purpose"}], answer="不知道", assistance_level=0, exposed=False, independent_task=True)
        self.assertEqual(assess_evidence(result, **args)["status"], "uncertain")
        result.criteria.append(result.criteria[0])
        with self.assertRaises(CourseGraphError):
            assess_evidence(result, **args)


if __name__ == "__main__":
    unittest.main()
