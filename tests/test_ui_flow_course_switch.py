"""Automatic teaching result isolation across real SPA course navigation."""
import asyncio
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from learning_agent.acceptance_course import AcceptanceCourseStore, DEMO_ID
from learning_agent.course_catalog import create_course, resolve_course
from pliac.learning_plan import PlanProposal
from pliac.tutor import TeachingProposal
from test_learning_workspace import platform_fixture, publish_synthetic
from test_ui_documents import isolated_application


def main():
    started, release = threading.Event(), threading.Event()
    calls = []

    async def planner(context, config):
        node = context['nodes'][0]['id']
        return PlanProposal(status='proposed', summary='Synthetic learning scope',
                            target_node_ids=[node], learning_order=[node], start_node_id=node,
                            rationale='Synthetic scope test', clarification=''), {'model': 'synthetic'}

    async def model(context, config):
        course = context['course']['id']
        calls.append((course, context['trigger']['reason']))
        if course == DEMO_ID:
            started.set()
            for _ in range(3000):
                if release.is_set():
                    break
                await asyncio.sleep(.01)
            else:
                raise TimeoutError('Synthetic A result was not released')
        return TeachingProposal(response='Automatic activity for ' + course,
                                action='probe', target_node_id=context['current_node_id'],
                                blocks=[], rationale='Synthetic check', question='Explain the concept',
                                uncertainty='Not a mastery judgement'), {'model': 'synthetic'}

    with tempfile.TemporaryDirectory() as folder, isolated_application(Path(folder)) as (base, root, _):
        ident = create_course(root, 'Synthetic flow B')['course']['id']
        second = resolve_course(root, ident)
        graph = platform_fixture()
        graph.update(id=ident, title='Synthetic flow B', version=1)
        publish_synthetic(second, graph)
        with (patch('pliac.tutor_api.configured_api', return_value=None),
              patch('pliac.learning_plan.generate_plan', planner),
              patch('pliac.tutor_api.generate_teaching', model), sync_playwright() as runtime):
            browser = runtime.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1100})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def adopt_scope(goal):
                page.get_by_role('button', name='设置学习起点').click()
                page.get_by_label('学习目标', exact=True).fill(goal)
                page.get_by_role('button', name='保存目标与起点').click()
                page.get_by_role('region', name='学习范围规划').get_by_role('button', name='按这个范围开始学习').click()

            try:
                page.goto(base + '/app/courses/' + DEMO_ID)
                adopt_scope('Synthetic goal A')
                assert started.wait(5), 'Verify A is actually generating before navigation'
                student = page.evaluate("localStorage.getItem('pliac.local-learner')")
                page.get_by_role('link', name='返回课程', exact=True).click()
                page.locator(f'a[href="/app/courses/{ident}"]').click()
                expect(page.locator('.course-name')).to_have_text('Synthetic flow B')
                adopt_scope('Synthetic goal B')
                flow = page.get_by_role('region', name='智能体学习进程')
                flow.get_by_role('link', name='打开当前学习活动').click()
                expect(page.locator('.teaching-material')).to_contain_text('Automatic activity for ' + ident)
                page.get_by_role('button', name='切换教学对话').click()
                page.get_by_label('当前课程的问题草稿').fill('B draft must survive A completion')
                second_before = second._read_learner(student)
                release.set()
                # Observe A persisted completion while B remains mounted, not merely after leaving B.
                page.wait_for_function('''async url => {
                    const response = await fetch(url);
                    if (!response.ok) return false;
                    const state = await response.json();
                    return state.workspace.tutor_turns?.length === 1;
                }''', arg=f'/api/learning?course_id={DEMO_ID}&student_id={student}', timeout=15000)
                expect(page.locator('.course-name')).to_have_text('Synthetic flow B')
                expect(page.locator('.teaching-material')).to_contain_text('Automatic activity for ' + ident)
                expect(page.locator('.teaching-material')).not_to_contain_text('Automatic activity for ' + DEMO_ID)
                expect(page.get_by_label('当前课程的问题草稿')).to_have_value('B draft must survive A completion')
                # Returning to A and refreshing must recover its activity without another generation.
                page.goto(base + '/app/courses/' + DEMO_ID)
                page.get_by_role('region', name='智能体学习进程').get_by_role('link', name='打开当前学习活动').click()
                expect(page.locator('.teaching-material')).to_contain_text('Automatic activity for ' + DEMO_ID)
                page.reload()
                expect(page.locator('.teaching-material')).to_contain_text('Automatic activity for ' + DEMO_ID)
                first = AcceptanceCourseStore(root)._read_learner(student)
                assert len(first['workspace']['tutor_turns']) == 1
                assert len(first['workspace']['assessments']) == 1
                assert not first['evidence'] and not first['diagnoses']
                assert second._read_learner(student) == second_before
                assert calls.count((DEMO_ID, 'plan_accepted')) == calls.count((ident, 'plan_accepted')) == 1
                page.get_by_role('link', name='返回课程', exact=True).click()
                page.locator(f'a[href="/app/courses/{ident}"]').click()
                page.get_by_role('button', name='切换教学对话').click()
                expect(page.get_by_label('当前课程的问题草稿')).to_have_value('B draft must survive A completion')
                page.get_by_role('region', name='智能体学习进程').get_by_role('link', name='打开当前学习活动').click()
                expect(page.locator('.teaching-material')).to_contain_text('Automatic activity for ' + ident)
                expect(page.locator('.teaching-material')).not_to_contain_text('Automatic activity for ' + DEMO_ID)
                assert not errors, errors
            finally:
                release.set()
                browser.close()
    print('PASS automatic A/B scope and activity isolation, persisted recovery, one generation and preserved B draft')


if __name__ == '__main__':
    main()
