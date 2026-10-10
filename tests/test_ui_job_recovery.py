"""Actual protected admin recovery UI; isolated synthetic jobs, no model calls."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from pliac.teaching_jobs import TeachingJobs
from test_ui_documents import isolated_application


def main():
    secret = 'synthetic-job-recovery-' + 'x' * 32
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
        'PLIAC_REQUIRE_AUTH': '1', 'PLIAC_ADMIN_SECRET': secret,
    }):
        with isolated_application(Path(folder)) as (base, store, _), sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get('PLIAC_BROWSER_CHANNEL') or None)
            context = browser.new_context()
            assert context.request.post(base + '/api/access/admin', data={'secret': secret}).ok
            jobs = TeachingJobs(store)
            for _ in range(3):
                owner, _ = jobs.claim('synthetic', 'stuck-job', 'unchanged-context')
                jobs.update('synthetic', 'stuck-job', owner, 'failed')
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/app/admin/job-recovery')
            expect(page.get_by_role('heading', name='教学生成任务恢复')).to_be_visible()
            # Empty course selects the default isolated store through the API.
            page.get_by_label('课程编号').fill(' ')
            page.get_by_label('学习者匿名编号').fill('synthetic')
            page.get_by_label('任务请求编号').fill('stuck-job')
            page.get_by_role('button', name='读取任务状态').click()
            expect(page.get_by_text('状态：failed；已尝试 3 次，当前上限 3 次。')).to_be_visible()
            button = page.get_by_role('button', name='允许原任务再重试三次')
            expect(button).to_be_disabled()
            page.get_by_label('检查结果与恢复原因').fill('Synthetic configuration checked; no provider called.')
            button.click()
            expect(page.get_by_role('status')).to_contain_text('没有自动调用模型')
            expect(button).to_be_disabled()
            status = jobs.status('synthetic', 'stuck-job')
            assert status['attempts'] == 3 and status['retry_limit'] == 6
            assert status['status'] == 'interrupted'
            page.get_by_role('button', name='读取任务状态').click()
            expect(page.get_by_text('状态：interrupted；已尝试 3 次，当前上限 6 次。')).to_be_visible()
            assert not errors, errors
            browser.close()
    print('Protected recovery UI passed; no model or real learner used.')


if __name__ == '__main__':
    main()
