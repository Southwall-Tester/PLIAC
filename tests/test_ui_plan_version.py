"""Real temporary course updates; synthetic planning, no paid calls."""
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from test_learning_workspace import platform_fixture, publish_synthetic
from pliac.workspace import LearningWorkspace
from pliac.learning_plan import PlanProposal
from pliac.tutor import TeachingProposal


def main():
    calls = []

    async def planner(context, config):
        calls.append('plan')
        ids = [node['id'] for node in context['nodes']]
        return PlanProposal(status='proposed', summary='更新后的合成学习范围', target_node_ids=ids,
            learning_order=ids, start_node_id=ids[0], rationale='合成规划', clarification=''), {'model': 'synthetic'}

    async def tutor(context, config):
        calls.append('teach')
        return TeachingProposal(response='新版本合成教学', target_node_id=context['current_node_id'],
            action='probe', rationale='合成起点核验', blocks=[], question='合成问题', uncertainty='仅工程验证'), {'model': 'synthetic'}

    with tempfile.TemporaryDirectory(prefix='pliac-plan-version-') as folder:
        with isolated_application(Path(folder)) as (base, store, _), patch('pliac.tutor_api.configured_api', return_value=None), patch('pliac.learning_plan.generate_plan', planner), patch('pliac.tutor_api.generate_teaching', tutor), sync_playwright() as p:
            graph = platform_fixture()
            current = store.load_graph('draft')
            graph.update(id=current['id'], version=current['version'])
            publish_synthetic(store, graph)
            course = store.load_graph()['id']
            service = LearningWorkspace(store)
            service.onboard({'student_id': 'synthetic-version', 'request_id': uuid.uuid4().hex,
                'expected_version': 0, 'course_version': store.load_graph()['version'], 'goals': '保留的学习目标',
                'background': '保留的基础', 'plan_mode': 'systematic', 'preferred_form': 'practice', 'agent_guided': True})

            def revise():
                graph = store.load_graph('draft')
                graph['nodes'][0]['description'] += ' Synthetic update.'
                publish_synthetic(store, graph)

            revise()
            browser = p.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.add_init_script("localStorage.setItem('pliac.local-learner','synthetic-version')")
            page.goto(base + '/app/courses/' + course)
            planning = page.get_by_role('region', name='学习范围规划')
            expect(planning).to_contain_text('旧规划请求已不适用')
            assert calls == []
            planning.get_by_role('link', name='调整目标与范围').click()
            expect(page.get_by_role('textbox', name='学习目标', exact=True)).to_have_value('保留的学习目标')
            expect(page.get_by_label('教学形式偏好')).to_have_value('practice')
            expect(page.get_by_label('学习范围类型')).to_have_value('systematic')
            page.get_by_role('button', name='保存目标与起点').click()
            expect(planning.get_by_role('button', name='按这个范围开始学习')).to_be_visible()
            assert calls == ['plan']
            planning.get_by_role('button', name='按这个范围开始学习').click()
            expect(page.get_by_role('link', name='打开当前学习活动')).to_be_visible()
            assert calls == ['plan', 'teach']
            saved = store.load_learner('synthetic-version')['workspace']['learning_plans'][0]
            revise()
            page.reload()
            expect(page.get_by_role('heading', name='先确认更新后的学习范围')).to_be_visible()
            expect(page.get_by_role('link', name='重新协商学习范围')).to_be_visible()
            assert calls == ['plan', 'teach']
            assert store.load_learner('synthetic-version')['workspace']['learning_plans'][0] == saved
            assert not errors, errors
            browser.close()
    print('PASS stale request makes no model call; goal/preferences preserved; new plan and teaching work; stale active scope retains history')


if __name__ == '__main__':
    main()
