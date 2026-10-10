"""Actual admin activation flow with isolated graph and synthetic audit model."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from test_course_graph import fixture
from pliac.knowledge_activation import KnowledgeAudit


def main():
    calls = []
    async def audit(context, config):
        calls.append(context)
        return KnowledgeAudit(checks=[{'key': item['key'], 'outcome': 'supported', 'reason': 'Synthetic only',
            'citations': [{'source_id': 'book', 'quote': 'Synthetic source'}]} for item in context['items']]), {'model': 'synthetic'}
    secret = 'synthetic-activation-' + 'x' * 32
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'PLIAC_REQUIRE_AUTH': '1', 'PLIAC_ADMIN_SECRET': secret}), patch('pliac.tutor_api.configured_api', return_value=None), patch('pliac.knowledge_activation.audit_knowledge', side_effect=audit):
        with isolated_application(Path(folder)) as (base, store, _), sync_playwright() as p:
            graph = fixture()
            graph['sources'][0]['text'] = 'Synthetic source for engineering verification only.'
            graph['resources'][0]['source_ids'] = ['book']
            saved = store.save_graph(graph, store.load_graph('draft')['version'])['graph']
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 390, 'height': 844})
            assert context.request.post(base + '/api/access/admin', data={'secret': secret}).ok
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/app/knowledge-activation')
            page.get_by_role('button', name='读取课程核验状态').click()
            expect(page.get_by_text('尚未核验 · 已尝试 0 次')).to_be_visible()
            button = page.get_by_role('button', name='自动核验并生效', exact=True)
            expect(button).to_be_disabled()
            page.get_by_role('checkbox').check()
            button.click()
            expect(page.get_by_role('status')).to_contain_text('已自动生效')
            assert len(calls) == 1
            assert store.load_graph()['version'] == saved['version']
            page.reload()
            page.get_by_role('button', name='读取课程核验状态').click()
            expect(page.get_by_text('核验结果已保存 · 已尝试 1 次')).to_be_visible()
            page.get_by_role('checkbox').check()
            button.click()
            expect(page.get_by_role('status')).to_contain_text('已自动生效')
            assert len(calls) == 1
            page.get_by_text('任务与恢复信息', exact=True).click()
            page.get_by_role('link', name='打开此任务的管理恢复').click()
            expect(page.get_by_label('学习者匿名编号')).to_have_value('knowledge-activation')
            assert page.get_by_label('任务请求编号').input_value().startswith('activation-v')
            page.get_by_role('button', name='读取任务状态').click()
            expect(page.get_by_text('状态：generated；已尝试 1 次，当前上限 3 次。')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            graph = store.load_graph('draft')
            graph['sources'][0].pop('text')
            store.save_graph(graph, graph['version'])
            page.goto(base + '/app/knowledge-activation')
            page.get_by_role('button', name='读取课程核验状态').click()
            expect(page.get_by_role('status')).to_contain_text('实际来源正文')
            expect(page.get_by_role('button', name='自动核验并生效', exact=True)).to_have_count(0)
            assert len(calls) == 1
            assert store.load_graph()['version'] == saved['version']
            assert not errors, errors
            browser.close()
    print('PASS protected activation UI, real snapshot publication, cached retry and recovery deep link; synthetic model only')


if __name__ == '__main__':
    main()
