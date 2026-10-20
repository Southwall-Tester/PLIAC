"""Saved course graphs open from the catalog and Lab without model generation."""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from build_linux_course import COURSE_ID, DEST
from install_course_draft import install
from learning_agent.course_catalog import resolve_course
from learning_agent.course_graph import _atomic_json
from pliac.linux_lab import LinuxLab
from test_linux_lab import DESCRIPTOR, sample_report


def main():
    report = {"page_errors": [], "generation_requests": [], "checks": []}
    with tempfile.TemporaryDirectory() as tmp, isolated_application(Path(tmp)) as (base, store, documents):
        install(DEST / "course.json", store)
        course = resolve_course(store, COURSE_ID)
        draft = course.load_graph("draft")
        course.publish(draft["version"], "Synthetic publisher", "UI test", personal_use=True)
        published_path = course.output_dir / "published" / f"v{draft['version']}.json"
        published_bytes = published_path.read_bytes()
        student = "synthetic-graph-feedback"
        lab = LinuxLab(course)
        with patch.object(lab, "descriptor", return_value=DESCRIPTOR):
            run = lab.create(dict(student_id=student, mode="published", course_version=draft["version"], scene="space"))
        binding = run["binding"]
        _atomic_json(lab.directory(binding["binding_id"]) / "telemetry.json", sample_report(binding))
        lab.sync(binding["binding_id"], student)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
            page.on("request", lambda r: report["generation_requests"].append(r.url)
                    if r.method == "POST" and "/api/handouts" in r.url else None)
            page.add_init_script("""Object.defineProperty(window,'NetworkView',{
                get(){return this.__View},set(View){this.__View=class extends View{
                    constructor(...args){super(...args);window.__network=this;}
                }}});""")
            page.goto(base + "/courses")
            card = page.locator(f'[data-course-id="{COURSE_ID}"]')
            expect(card.locator(".graph-course")).to_have_attribute("href", "/knowledge?course_id=" + COURSE_ID)
            card.locator(".graph-course").click()
            page.wait_for_function("window.__network?.data?.nodes.length===55 && !window.__network.busy")
            expect(page.locator("#colorMode")).to_have_value("family")
            assert page.evaluate("new Set(__network.data.nodes.filter(n=>n.data.kind==='concept').map(n=>n.style.fill)).size") == 8
            expect(page.locator("#viewCount")).to_contain_text("按单元分色")
            page.locator("#filtersButton").click()
            page.locator("#colorMode").select_option("mastery")
            page.wait_for_function("__network.data.nodes.filter(n=>n.data.kind==='concept').every(n=>n.style.fill==='#bdc4ca') && !__network.busy")
            expect(page.locator("#viewCount")).to_contain_text("按确认状态分色")
            report["checks"].append("Unassessed course defaults to eight chapter colors; explicit unknown status is neutral gray")
            page.reload()
            page.wait_for_function("window.__network?.data?.nodes.length===55 && !window.__network.busy")
            report["checks"].append("Catalog and reload display saved course graph")
            page.goto(base + "/linux-lab?course_id=" + COURSE_ID + "&student_id=" + student)
            expect(page.locator("#readerLink")).to_have_attribute("href", "/knowledge?course_id=" + COURSE_ID + "&student_id=" + student)
            concept = page.locator('#stages a[href*="node_id=cp"]').first
            expect(concept).to_have_attribute("href", "/knowledge?course_id=" + COURSE_ID + "&node_id=cp&student_id=" + student)
            page.evaluate("localStorage.setItem('learningAgent.student','unrelated-legacy-student')")
            page.goto(base + concept.get_attribute("href"))
            expect(page.locator("#detailContent h2")).to_contain_text("cp")
            expect(page.locator("#studentId")).to_have_value(student)
            expect(page.locator("#detailContent")).to_contain_text("待核验")
            expect(page.locator("#colorMode")).to_have_value("auto")
            expect(page.locator(".auto-assessment")).to_have_attribute("data-level", "needs_practice")
            page.wait_for_function("window.__network?.data?.nodes.find(n=>n.id==='cp')?.style.fill===PracticeAssessment.colors.needs_practice")
            page.reload()
            expect(page.locator("#studentId")).to_have_value(student)
            expect(page.locator("#detailContent")).to_contain_text("待核验")
            # Correct the synthetic failure. The same persistent node changes
            # estimate without a graph generation request or new course version.
            report_data = sample_report(binding)
            report_data["operations"].append(dict(report_data["operations"][0], sequence=2,
                facts={"backup_hidden_present": True, "backup_nested_present": False}))
            report_data["operation_total"] = 2
            report_data["events"].append(dict(id=3, phase=2, kind="passed", at="2026-10-11T00:00:00Z",
                                               prompt_level=0, operation_cursor=2))
            report_data["phases_passed"] = 2
            report_data["input_patterns"] = [dict(id="synthetic-typos", kind="command_typo", command="cp",
                concept="copy", phase=2, phases=[2], attempts=3, episodes=2, resolved_episodes=2,
                active=False, at="2026-10-11T00:00:00Z", operation_cursor=2)]
            _atomic_json(lab.directory(binding["binding_id"]) / "telemetry.json", report_data)
            lab.sync(binding["binding_id"], student)
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(page.locator(".auto-assessment")).to_have_attribute("data-level", "developing")
            expect(page.locator(".fluency-summary")).to_contain_text("反复易错")
            page.wait_for_function("window.__network?.data?.nodes.find(n=>n.id==='cp')?.style.fill===PracticeAssessment.colors.developing")
            expect(page.locator(".auto-assessment")).to_contain_text("查看对应实训周目")
            report["checks"].append("Correction refreshes the existing node color and reasons without regenerating the graph")
            page.goto(base + "/knowledge?course_id=" + COURSE_ID + "&node_id=cp")
            expect(page.locator("#studentId")).to_have_value(student)
            expect(page.locator("#detailContent")).to_contain_text("待核验")
            expect(page.locator(".auto-assessment")).to_have_attribute("data-level", "developing")
            page.locator(".auto-assessment summary").click()
            expect(page.locator(".auto-assessment")).to_contain_text("任务环节用时")
            page.locator(".auto-assessment a").first.click()
            expect(page.locator('#masteryList [data-assessment-node="cp"]')).to_contain_text("初步掌握")
            expect(page.locator("#runs")).to_have_value(binding["binding_id"])
            page.locator('#masteryList [data-assessment-node="cp"] > summary').click()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
            output = ROOT / "outputs/verification/linux-mastery"
            output.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output / "synthetic-feedback-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})
            report["checks"].append("Persisted Lab feedback appears for the same learner after navigation and reload")
            report["checks"].append("Lab concept links select the existing course node")
            with patch.object(lab, 'descriptor', return_value=DESCRIPTOR):
                reference_run = lab.create(dict(student_id=student, mode='published', course_version=draft['version'], scene='space'))
            reference_binding = reference_run['binding']
            referenced = sample_report(reference_binding)
            referenced['lab_session_id'] = reference_binding['binding_id']
            referenced['events'].append(dict(id=3, phase=2, kind='passed', at='2026-10-11T00:03:00Z', prompt_level=0, operation_cursor=2))
            referenced['phases_passed'] = 2
            referenced['operations'].append(dict(referenced['operations'][0], sequence=2,
                at='2026-10-10T00:02:00Z', facts=dict(backup_hidden_present=True, backup_nested_present=False)))
            referenced['operation_total'] = 2
            referenced['reference_total'] = 1
            referenced['reference_lookups'] = [dict(sequence=1, phase=2, source='notes', topic='cp', at='2026-10-10T00:01:20Z', operation_cursor=1, after_completion=False)]
            _atomic_json(lab.directory(reference_binding['binding_id']) / 'telemetry.json', referenced)
            lab.sync(reference_binding['binding_id'], student)
            page.goto(base + '/knowledge?course_id=' + COURSE_ID + '&node_id=cp&student_id=' + student)
            expect(page.locator('.auto-assessment')).to_have_attribute('data-level', 'referenced')
            expect(page.locator('.reference-summary')).to_contain_text('成功操作前查阅')
            expect(page.locator('.assessment-dimensions > div')).to_have_count(5)
            expect(page.locator('.behavior-sequences')).to_contain_text('出错 → 查阅 → 修正并通过检查')
            expect(page.locator('.assessment-facets')).to_contain_text('隐藏文件完整性：修正后通过')
            expect(page.locator('[data-dimension="retention"]')).to_contain_text('等待后续独立复测')
            page.wait_for_function("window.__network?.data?.nodes.find(n=>n.id==='cp')?.style.fill===PracticeAssessment.colors.referenced")
            page.reload()
            expect(page.locator('.auto-assessment')).to_contain_text('参考资料完成')
            page.locator('.auto-assessment summary').click()
            page.locator('.auto-assessment a').first.click()
            expect(page.locator('#masteryList [data-assessment-node="cp"]')).to_contain_text('参考资料完成')
            report['checks'].append('Reference-assisted success persists with topic, evidence and matching graph/Lab color')
            with patch.object(lab, 'descriptor', return_value=DESCRIPTOR):
                followup_run = lab.create(dict(student_id=student, mode='published', course_version=draft['version'], scene='space'))
            followup_binding = followup_run['binding']
            followup = sample_report(followup_binding)
            followup['lab_session_id'] = followup_binding['binding_id']
            followup['events'][0]['at'] = '2026-10-12T00:00:00Z'
            followup['events'][-1] = dict(id=2, phase=2, kind='passed', at='2026-10-12T00:01:00Z', prompt_level=0, operation_cursor=1)
            followup['operations'][0].update(at='2026-10-12T00:00:30Z', facts=dict(backup_hidden_present=True, backup_nested_present=False))
            followup['phases_passed'] = 2
            _atomic_json(lab.directory(followup_binding['binding_id']) / 'telemetry.json', followup)
            lab.sync(followup_binding['binding_id'], student)
            page.goto(base + '/knowledge?course_id=' + COURSE_ID + '&node_id=cp&student_id=' + student)
            expect(page.locator('[data-dimension="retention"]')).to_contain_text('后续同类任务已无辅助通过')
            expect(page.locator('.behavior-followups a')).to_have_attribute('href',
                f'/linux-lab?course_id={COURSE_ID}&student_id={student}&binding_id={reference_binding["binding_id"]}')
            page.reload()
            expect(page.locator('.behavior-followups')).to_contain_text('后续周目无辅助通过')
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(output / 'synthetic-behavior-followup-mobile.png'), full_page=True)
            page.locator('.behavior-followups a').click()
            expect(page.locator('#runs')).to_have_value(reference_binding['binding_id'])
            report['checks'].append('Five evidence dimensions, copy facets and time-ordered independent follow-up survive reload and link to the prior run')
            page.goto(base + "/course-reader?course_id=" + COURSE_ID)
            expect(page.locator("#savedGraphLink")).to_have_attribute("href", "/knowledge?course_id=" + COURSE_ID)
            expect(page.locator("#scopeEmpty")).to_contain_text("已有课程图谱")
            page.locator("#savedGraphLink").click()
            page.wait_for_function("window.__network?.data?.nodes.length===55 && !window.__network.busy")
            report["checks"].append("Empty AI reader links back to the saved graph")
            assert not page.request.get(base + "/api/handouts?course_id=" + COURSE_ID).json()["jobs"]
            assert published_path.read_bytes() == published_bytes
            browser.close()
    assert not report["page_errors"] and not report["generation_requests"], report
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
