"""Delayed synthetic generation across actual SPA course navigation."""
import asyncio
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from learning_agent.acceptance_course import AcceptanceCourseStore, DEMO_ID
from learning_agent.course_catalog import create_course, resolve_course
from pliac.tutor import TeachingProposal
from test_learning_workspace import platform_fixture, publish_synthetic
from test_ui_documents import isolated_application


def main():
    release = threading.Event()
    started = threading.Event()
    calls = []

    async def model(context, config):
        course = context['course']['id']
        calls.append(course)
        if course == DEMO_ID:
            started.set()
            for _ in range(3000):
                if release.is_set():
                    break
                await asyncio.sleep(.01)
            else:
                raise TimeoutError('Synthetic release was not signaled')
        return TeachingProposal(response='Synthetic response for ' + course, action='probe',
            target_node_id=context['current_node_id'], blocks=[], rationale='Synthetic test',
            question='Synthetic question', uncertainty='Not a mastery judgement'), {'model': 'synthetic-switch'}

    with tempfile.TemporaryDirectory() as folder, isolated_application(Path(folder)) as (base, root, _):
        created = create_course(root, 'Synthetic second course')['course']['id']
        second = resolve_course(root, created)
        graph = platform_fixture()
        graph.update(id=created, title='Synthetic second course', version=1)
        publish_synthetic(second, graph)
        with patch('pliac.tutor_api.generate_teaching', model), patch('pliac.tutor_api.configured_api', return_value=None), sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            page = browser.new_page(viewport={'width': 1360, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(base + '/app/courses/' + DEMO_ID)
                page.get_by_role('button', name='切换教学对话').click()
                page.get_by_label('当前课程的问题草稿').fill('Course A pending question')
                page.get_by_role('button', name='发送学习问题').click()
                expect(page.locator('.conversation')).to_contain_text('正在组织课程讲解')
                assert started.wait(5), 'A model must be running before switching course'
                student = page.evaluate("localStorage.getItem('pliac.local-learner')")
                page.get_by_role('link', name='返回课程', exact=True).click()
                page.locator(f'a[href="/app/courses/{created}"]').click()
                expect(page.locator('.course-name')).to_have_text('Synthetic second course')
                page.get_by_role('button', name='切换教学对话').click()
                draft = page.get_by_label('当前课程的问题草稿')
                expect(draft).to_have_value('')
                draft.fill('Course B unsent draft')
                release.set()
                # The server may finish A after its browser request was aborted.
                page.get_by_role('button', name='发送学习问题').click()
                expect(page.locator('.conversation')).to_contain_text('Synthetic response for ' + created)
                draft.fill('Course B next draft')
                expect(page.locator('.conversation')).not_to_contain_text('Synthetic response for ' + DEMO_ID)
                state = second._read_learner(student)
                assert len(state['workspace']['tutor_turns']) == 1
                assert state['workspace']['tutor_turns'][0]['message'] == 'Course B unsent draft'
                assert not state['evidence'] and not state['diagnoses']
                page.go_back()
                page.go_back()
                page.get_by_role('button', name='切换教学对话').click()
                expect(page.locator('.conversation')).to_contain_text('Synthetic response for ' + DEMO_ID)
                expect(page.locator('.conversation')).not_to_contain_text('Synthetic response for ' + created)
                first = AcceptanceCourseStore(root)._read_learner(student)
                assert len(first['workspace']['tutor_turns']) == 1
                assert calls.count(DEMO_ID) == calls.count(created) == 1
                page.get_by_role('link', name='返回课程', exact=True).click()
                page.locator(f'a[href="/app/courses/{created}"]').click()
                page.get_by_role('button', name='切换教学对话').click()
                expect(page.get_by_label('当前课程的问题草稿')).to_have_value('Course B next draft')
                assert not errors, errors
            finally:
                release.set()
                browser.close()
    print('PASS delayed A response cannot overwrite B; separate server histories and drafts; one model call per course')


if __name__ == '__main__':
    main()
