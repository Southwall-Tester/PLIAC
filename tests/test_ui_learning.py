"""Real-browser platform flow, with synthetic review and isolated runtime data."""
import json
import tempfile
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

from test_ui_documents import isolated_application
from test_learning_workspace import platform_fixture, publish_synthetic

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "verification"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "persistent_course_store_used": False, "checks": [], "page_errors": [], "screenshots": []}
    def passed(text):
        report["checks"].append(text)
        print("PASS", text, flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix="pliac-learning-ui-") as temporary:
            directory = Path(temporary)
            graph = platform_fixture()
            graph["title"] = "监督分类 · 合成验证课程"
            graph["chapters"][0]["title"] = "数据与评估"
            graph["chapters"][1]["title"] = "模型与泛化"
            for node, title, description in zip(graph["nodes"],
                ["样本、特征与标签", "训练集与验证集", "分类树的复杂度", "欠拟合与过拟合"],
                ["样本是一次观测；特征是预测时可用的输入，标签是希望预测的目标。",
                 "训练集用于拟合模型，验证集用于比较候选设置；测试集保留到最后进行独立评估。",
                 "分类树通过逐层划分特征空间完成预测，树的深度影响拟合能力。",
                 "同时观察训练与验证表现，区分模型能力不足和对训练数据过度适应。"]):
                node.update(title=title, description=description)
            graph["nodes"][0]["check_question"] = "用设备温度和振动预测是否故障时，哪些是特征，哪个是标签？请说明理由。"
            graph["nodes"][0]["check_task"]["hint_levels"] = ["先检查输入与预测目标的区分。", "预测时能获得哪些信息？", "把输入与事后结果分开。", "列出预测时可用的观测值。"]
            graph["nodes"][1]["check_question"] = "为什么不能根据测试集表现反复选择模型？请说明验证集的作用。"
            seed = directory / "seed.json"
            seed.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
            with isolated_application(directory) as (base, store, _documents):
                store.seed_path = seed
                publish_synthetic(store)
                with httpx.Client(base_url=base, timeout=15) as client, sync_playwright() as p:
                    browser = p.chromium.launch()
                    page = browser.new_page(viewport={"width":1440, "height":1000})
                    page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
                    page.goto(base + '/courses')
                    page.locator(f'[data-course-id="{graph["id"]}"] .learning-course').click()
                    page.locator('#studentId').fill('synthetic-ui')
                    page.locator('#identityForm button[type=submit]').click()
                    expect(page.locator('#onboarding')).to_be_visible()
                    expect(page.locator('.toolbar a[href*="ml-lab"]')).to_have_count(0)
                    expect(page.locator('#courseLabs')).to_have_attribute('data-ready','true')
                    expect(page.locator('#courseLabs')).to_be_hidden()
                    expect(page.locator('#courseLabList a')).to_have_count(0)
                    page.locator('#goals').fill('能独立解释数据划分的作用，并应用于分类任务。')
                    page.locator('#background').fill('了解基础 Python，正在学习机器学习。')
                    page.locator('#interests').fill('科幻，音乐')
                    page.locator('#selfAssessments').locator('..').locator('summary').click()
                    page.locator('[data-assess="a"]').select_option('confident')
                    page.locator('#onboardForm button[type=submit]').click()
                    expect(page.locator('#onboarding')).not_to_be_visible()
                    page.locator('#nextLesson').click()
                    expect(page.locator('#questionText')).to_contain_text('设备温度')
                    assert store.load_learner('synthetic-ui')['states']['a']['status'] == 'uncertain'
                    passed('Initial profile and self-assessment do not manufacture mastery; first lesson uses course content')

                    page.locator('#answerText').fill('温度和振动是输入，是否故障是希望预测的结果。草稿尚未完成。')
                    expect(page.locator('#saveStatus')).to_have_text('已保存到本机')
                    page.reload()
                    page.locator('#identityForm button[type=submit]').click()
                    expect(page.locator('#answerText')).to_have_value('温度和振动是输入，是否故障是希望预测的结果。草稿尚未完成。')
                    passed('Reload restores the active lesson and autosaved answer draft')

                    page.locator('#hintButton').click()
                    expect(page.locator('#promptBadge')).to_have_text('已使用 1 级提示')
                    page.locator('#answerText').fill('温度和振动属于预测时可取得的特征，是否故障属于类别标签。')
                    page.locator('#answerConfidence').select_option('sure')
                    page.locator('#answerForm button[type=submit]').click()
                    expect(page.locator('#responses')).to_contain_text('等待复核')
                    expect(page.locator('#answerText')).to_have_value('')
                    page.locator('[data-paragraph="concept"]').click()
                    page.locator('#annotationQuestion').fill('预测之后才取得的信息为什么不能作为特征？')
                    page.locator('#annotationForm button[type=submit]').click()
                    expect(page.locator('#annotationDialog')).not_to_be_visible()
                    expect(page.locator('#lessonContent')).to_contain_text('已记录 1 处困惑')
                    assert store.load_learner('synthetic-ui')['evidence'][-2]['prompt_level'] == 1
                    passed('Hints, learner answers and paragraph annotations persist with separate provenance')
                    page.screenshot(path=str(OUTPUT / 'learning-workspace-desktop.png'), full_page=True)
                    report['screenshots'].append('learning-workspace-desktop.png')

                    review = browser.new_page(viewport={"width":1440, "height":1000})
                    review.on('pageerror', lambda e: report['page_errors'].append(str(e)))
                    review.goto(base + '/review')
                    review.locator('#studentId').fill('synthetic-ui')
                    review.locator('#identityForm button[type=submit]').click()
                    expect(review.locator('.evidence-entry')).to_have_count(3)
                    for item in review.locator('[data-evidence]').all(): item.check()
                    review.locator('#reviewStatus').select_option('mastered')
                    review.locator('#reviewBasis').fill('Synthetic verification: attempt invalid mastery with prompted evidence.')
                    review.locator('#reviewer').fill('Synthetic reviewer')
                    review.locator('#reviewForm button[type=submit]').click()
                    expect(review.locator('#workspaceError')).to_contain_text('独立完成')
                    review.locator('#reviewStatus').select_option('needs_review')
                    review.locator('#reviewBasis').fill('合成复核：结合任务回答与困惑记录，安排一次减少提示的新题核验。')
                    review.locator('#reviewForm button[type=submit]').click()
                    expect(review.locator('#diagnosisHistory')).to_contain_text('需要补学')
                    page.locator('#refreshButton').click()
                    expect(page.locator('[data-node="a"] .state-dot')).to_have_class('state-dot needs_review')
                    passed('Teacher review rejects hinted mastery and updates the same graph state used by the learner')

                    page.locator('[data-node="b"]').click()
                    expect(page.locator('#questionText')).to_contain_text('测试集')
                    page.locator('#recallToggle').click()
                    page.locator('#answerText').fill('验证集用于选择设置，测试集只在最终评估时使用，否则会把测试信息带入模型选择。')
                    page.locator('#answerConfidence').select_option('sure')
                    page.locator('#answerForm button[type=submit]').click()
                    expect(page.locator('#responses')).to_contain_text('等待复核')
                    review.locator('#refreshButton').click()
                    review.locator('#reviewNode').select_option('b')
                    expect(review.locator('[data-evidence]')).to_have_count(1)
                    review.locator('[data-evidence]').check()
                    review.locator('#reviewStatus').select_option('mastered')
                    review.locator('#reviewBasis').fill('合成复核：独立说明验证集选择与测试集最终评估的区别。')
                    review.locator('#reviewForm button[type=submit]').click()
                    expect(review.locator('#diagnosisHistory')).to_contain_text('当前已掌握')
                    passed('Independent task evidence can support a human-reviewed mastery decision')

                    review.locator('[data-policy-node="b"]').check()
                    review.locator('#policyAuthor').fill('Synthetic course teacher')
                    review.locator('#policyBasis').fill('Synthetic narrow acceptance rule for this browser test.')
                    review.locator('#policyForm button[type=submit]').click()
                    expect(review.locator('#saveStatus')).to_contain_text('规则草稿已保存')
                    graph = store.load_graph('draft')
                    response = client.post('/api/course-graph/publish', json={'expected_version':graph['version'], 'published_by':'Synthetic publisher', 'note':'Synthetic rule publication'})
                    response.raise_for_status()
                    page.locator('#refreshButton').click()
                    expect(page.locator('#notice')).to_contain_text('新发布版本')
                    expect(page.locator('.report-row').first).to_contain_text('当前达标')
                    page.locator('[data-report="ch1"]').click()
                    expect(page.locator('#chapterReports')).to_contain_text('已保存 1 份报告')
                    with page.expect_download() as exported:
                        page.locator('#exportButton').click()
                    data = json.loads(Path(exported.value.path()).read_text(encoding='utf-8'))
                    assert data['workspace']['reports'][0]['passed'] is True
                    assert data['workspace']['reports'][0]['nodes'][1]['evidence_ids']
                    passed('Published course policy controls chapter progression; saved reports and exports retain evidence references')

                    review.locator('#refreshButton').click()
                    review.locator('#taskNode').select_option('c')
                    review.locator('#taskQuestion').fill('新的合成诊断题：限制树深度会影响哪类表现？')
                    review.locator('#taskAnswer').fill('合成教师参考：分别比较训练与验证表现。')
                    review.locator('#taskRubric').fill('合成判据：区分两种数据集的表现。')
                    for i in range(1,5): review.locator(f'#taskHint{i}').fill(f'合成提示 {i}')
                    review.locator('#taskEditorForm button[type=submit]').click()
                    expect(review.locator('#saveStatus')).to_contain_text('任务草稿已保存')
                    assert store.load_graph('draft')['nodes'][2]['review_status'] == 'draft'
                    assert store.load_graph()['nodes'][2]['check_task']['version'] == 1
                    passed('Teacher can author versioned diagnostic questions; edits remain draft until renewed review and publication')

                    page.locator('[data-node="a"]').click()
                    expect(page.locator('#promptBadge')).to_have_text('已使用 1 级提示')
                    page.locator('#themeButton').click()
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile overflow'
                    page.screenshot(path=str(OUTPUT / 'learning-workspace-mobile-dark.png'), full_page=True)
                    report['screenshots'].append('learning-workspace-mobile-dark.png')
                    review.screenshot(path=str(OUTPUT / 'learning-review-desktop.png'), full_page=True)
                    report['screenshots'].append('learning-review-desktop.png')
                    passed('Reopening a seen question preserves hint exposure; mobile and dark-theme layouts fit the viewport')
                    assert not report['page_errors'], report['page_errors']
                    browser.close()
    finally:
        (OUTPUT / 'learning-workspace-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
