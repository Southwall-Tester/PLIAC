"""Synthetic browser retest loop preserves history and explains state updates."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application, ROOT
from test_learning_workspace import platform_fixture, publish_synthetic
from pliac.tutor import AssessmentProposal


def main(version_change=False):
    async def model(record, config):
        passed = record['answer'] == 'synthetic corrected answer'
        return AssessmentProposal(criteria=[{'criterion_id': item['id'], 'outcome': 'met' if passed else 'not_met',
            'quote': record['answer'], 'reason': 'Synthetic rubric evaluation'} for item in record['rubric']],
            feedback='合成复测通过' if passed else '合成初测发现问题', follow_up_question=''), {'model': 'synthetic'}

    with tempfile.TemporaryDirectory(prefix='retest-ui-') as directory:
        with isolated_application(Path(directory)) as (base, store, _), patch('pliac.tutor_api.configured_api', return_value=object()), patch('pliac.tutor_api.evaluate_answer', model), sync_playwright() as playwright:
            graph = platform_fixture()
            current = store.load_graph('draft')
            graph.update(id=current['id'], version=current['version'])
            node = graph['nodes'][0]
            node['retest_tasks'] = [{'id': 'retest-a', 'version': 1, 'question': '新的独立合成核验任务',
                                    'rubric': node['check_task']['rubric'], 'hint_levels': ['a', 'b', 'c', 'd']}]
            publish_synthetic(store, graph)
            browser = playwright.chromium.launch(channel=os.environ.get('PLIAC_BROWSER_CHANNEL') or None)
            page = browser.new_page(viewport={'width': 1440, 'height': 1100})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/app/courses/' + graph['id'])
            panel = page.get_by_role('region', name='理解核验')
            panel.get_by_role('button', name='开始核验').click()
            for answer, expected in [('synthetic wrong answer', '发现需要补学的内容'), ('synthetic corrected answer', '本任务证据支持掌握')]:
                panel.get_by_role('textbox', name='你的解释').fill(answer)
                panel.get_by_role('button', name='保存作答').click()
                panel.get_by_role('button', name='按标准评价').click()
                expect(panel.get_by_role('heading', name=expected)).to_be_visible()
                if answer == 'synthetic wrong answer':
                    page.goto(base + '/app/')
                    reminders = page.get_by_role('region', name='复习与核验提醒')
                    expect(reminders).to_contain_text('需要补学')
                    reminders.get_by_role('link').first.click()
                    expect(panel.get_by_role('heading', name=expected)).to_be_visible()
                    if version_change:
                        updated = store.load_graph('draft')
                        updated['nodes'][0]['description'] += ' Revised synthetic course scope.'
                        publish_synthetic(store, updated)
                        page.reload()
                        panel.get_by_role('button', name='开始核验').click()
                    else:
                        panel.get_by_role('button', name='继续核验').click()
                    expect(panel).to_contain_text('新的独立合成核验任务')
            if version_change:
                expect(panel).not_to_contain_text('已覆盖 1 条历史问题')
            else:
                expect(panel).to_contain_text('已覆盖 1 条历史问题')
            memory = page.get_by_role('region', name='学习记忆')
            memory.locator('summary').click()
            expect(memory).to_contain_text('不参与当前掌握或冲突判断' if version_change else '这条历史问题已由后续独立核验覆盖')
            student = page.evaluate("localStorage.getItem('pliac.local-learner')")
            learner = store.load_learner(student)
            assert learner['states']['a']['status'] == 'mastered'
            assert len(learner['evidence']) == 2 and len(learner['diagnoses']) == 2
            assert learner['diagnoses'][0]['status'] == 'needs_review'
            return_url = page.url
            page.goto(base + '/app/')
            expect(page.get_by_role('region', name='复习与核验提醒')).to_contain_text('目前没有待处理提醒')
            page.goto(return_url)
            page.get_by_role('button', name='保存阶段学习总结').click()
            report = page.locator('.stage-report')
            report.get_by_text('查看原始作答与诊断依据').first.click()
            expect(report).to_contain_text('不参与当时的掌握或冲突判断' if version_change else '保存报告前已由后续独立核验覆盖')
            assert not errors, errors
            browser.close()
            print(f'PASS independent retest, history notice, current mastery, retained evidence and report; course_changed={version_change}')


if __name__ == '__main__':
    main()
    main(version_change=True)
