"""Protected real API, two synthetic identities, no model or camera calls."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from test_ui_access import enter_created


def main():
    with tempfile.TemporaryDirectory(prefix='pliac-support-ui-') as folder, patch.dict(os.environ, {'PLIAC_REQUIRE_AUTH': '1'}):
        with isolated_application(Path(folder)) as (base, _, _), sync_playwright() as p:
            browser = p.chromium.launch()
            for choice in ('continue', 'hint'):
                context = browser.new_context(viewport={'width': 1360, 'height': 1000})
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base + '/app/courses/ml_acceptance_demo?lab=1')
                page.get_by_role('button', name='创建匿名学习档案').click()
                enter_created(page)
                lab = page.get_by_role('article', name='机器学习实验')
                lab.get_by_role('button', name='开始实验', exact=True).click()
                lab.get_by_label('预测目标', exact=True).select_option('receipt')
                lab.get_by_label('预测输入', exact=True).select_option('receipt')
                lab.get_by_label('回执产生时间').select_option('before')
                student = page.evaluate("localStorage.getItem('pliac.local-learner')")
                url = base + f'/api/ml-lab?course_id=ml_acceptance_demo&student_id={student}'
                for expected in (1, 2):
                    lab.get_by_role('button', name='检查本步成果').click()
                    expect(lab.get_by_role('button', name='检查本步成果')).to_be_enabled()
                    assert len(page.request.get(url).json()['active']['checks']) == expected
                offer = page.get_by_role('region', name='实验帮助邀请')
                expect(offer).to_be_visible()
                offer.get_by_role('button', name='我想继续尝试' if choice == 'continue' else '查看分步提示').click()
                expect(offer).to_have_count(0)
                saved = page.request.get(url).json()['active']
                assert saved['support_choices']['inspect']['choice'] == choice
                assert saved['hints']['inspect'] == (2 if choice == 'continue' else 3)
                page.reload()
                expect(lab).to_contain_text('已完成 0 / 5 步')
                page.goto(base + '/app/')
                continuation = page.get_by_role('region', name='继续学习').get_by_role('link').filter(has_text='继续未完成的实验')
                expect(continuation).to_have_count(1)
                continuation.click()
                expect(lab).to_contain_text('已完成 0 / 5 步')
                assert page.request.get(url).json()['active']['id'] == saved['id']
                expect(offer).to_have_count(0)
                if choice == 'hint':
                    expect(lab).to_contain_text('提示 3：')
                page.goto(base + '/app/archive?kind=lab')
                expect(page.locator('.archive-entry')).to_have_count(1)
                page.get_by_text('查看本轮实验记录', exact=True).click()
                expect(page.locator('.archive-entry')).to_contain_text('本轮未完成')
                expect(page.locator('.archive-entry')).to_contain_text('成果检查未通过')
                expect(page.locator('.archive-entry')).to_contain_text('本轮未封存测试结果')
                page.reload()
                expect(page.get_by_label('查看内容')).to_have_value('lab')
                page.get_by_role('link', name='打开当前实验（不切换历史轮次）').click()
                expect(lab).to_contain_text('已完成 0 / 5 步')
                assert page.request.get(url).json()['active']['id'] == saved['id']
                assert not errors, errors
                context.close()
            browser.close()
    print('PASS protected help invitation; explicit accept/decline persisted; no extra help for decline; refresh does not repeat invitation')


if __name__ == '__main__':
    main()
