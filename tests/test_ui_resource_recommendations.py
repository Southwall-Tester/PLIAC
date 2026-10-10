"""A simulated agent selects an actual course PDF through real protected APIs."""
import os
import copy
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from pliac.tutor import TeachingProposal, ResourceRecommendation
from test_resource_document import prepare_pdf
from test_learning_workspace import publish_synthetic
from test_ui_access import enter_created
from test_ui_documents import isolated_application


def main():
    calls = []
    async def model(context, config):
        calls.append(context)
        assert context['resources'][0]['id'] == 'r_a'
        return TeachingProposal(response='合成教学：可以先查看课件，再解释自己的理解。', target_node_id='a',
            action='explain', rationale='合成资料选择测试', blocks=[], question='', uncertainty='不是教学效果试验',
            recommended_resources=[ResourceRecommendation(resource_id='r_a', reason='合成理由：用原页对照当前概念。'),
                ResourceRecommendation(resource_id='video_reference', reason='合成片段推荐')]), {'model': 'synthetic'}

    with tempfile.TemporaryDirectory(prefix='pliac-resource-agent-') as folder, patch.dict(os.environ, {'PLIAC_REQUIRE_AUTH': '1'}):
        with isolated_application(Path(folder)) as (base, store, documents), patch('pliac.tutor_api.configured_api', return_value=None), patch('pliac.tutor_api.generate_teaching', model), sync_playwright() as p:
            _, graph = prepare_pdf(store, documents)
            video = copy.deepcopy(graph['resources'][0])
            video.update(id='video_reference', title='合成视频参考', format='video',
                url='https://media.example.test/lesson.webm', video_segment={'start_seconds': 12, 'end_seconds': 50})
            graph['resources'].append(video)
            publish_synthetic(store, graph)
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1400, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/app/courses/' + graph['id'])
            page.get_by_role('button', name='创建匿名学习档案').click()
            enter_created(page)
            page.get_by_role('button', name='切换教学对话').click()
            page.locator('.composer textarea').fill('有没有合适的学习资料？')
            page.get_by_role('button', name='发送学习问题').click()
            turn = page.locator('.tutor-turn').last
            turn.get_by_text('本次建议的学习材料', exact=True).click()
            expect(turn).to_contain_text('合成理由：用原页对照当前概念。')
            expect(turn).to_contain_text('当时推荐片段：12—50 秒')
            link = turn.get_by_role('button', name='查看推荐材料：合成 PDF 课件')
            link.click()
            page.get_by_role('button', name='在工作台阅读原文件（PDF）').click()
            expect(page.get_by_role('img', name='原文件第 2 页')).to_be_visible()
            page.get_by_role('button', name='关闭材料选择').click()
            expect(link).to_be_focused()
            student = page.evaluate("localStorage.getItem('pliac.local-learner')")
            learner = store._read_learner(student)
            material = learner['workspace']['tutor_turns'][-1]['request_id']
            assert learner['evidence'] == [] and learner['diagnoses'] == []
            target = base + f"/app/courses/{graph['id']}?material={material}"
            page.goto(target)
            body = page.locator('.teaching-material')
            body.get_by_text('本次建议的学习材料', exact=True).click()
            expect(body).to_contain_text('合成理由：用原页对照当前概念。')
            expect(body).to_contain_text('当时推荐片段：12—50 秒')
            graph = store.load_graph('draft'); graph['resources'] = []
            publish_synthetic(store, graph)
            page.reload()
            body.get_by_text('本次建议的学习材料', exact=True).click()
            body.get_by_role('button', name='查看推荐材料：合成 PDF 课件').click()
            dialog = page.get_by_role('dialog', name='选择学习材料')
            expect(dialog).to_contain_text('该推荐材料目前不再关联此知识点或已不可用')
            expect(dialog.get_by_role('button', name='在工作台阅读原文件（PDF）')).to_have_count(0)
            page.keyboard.press('Escape')
            expect(body).to_contain_text('合成理由：用原页对照当前概念。')
            expect(body).to_contain_text('当时推荐片段：12—50 秒')
            assert len(calls) == 1
            assert not errors, errors
            browser.close()
    print('PASS simulated agent resource choice, actual protected PDF open, chat/material persistence, focus return, removed-resource warning; no learner mastery from reading')


if __name__ == '__main__':
    main()
