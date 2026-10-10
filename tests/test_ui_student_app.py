"""React navigation, persisted drafts and themes against an isolated real API."""
import json
import os
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/verification"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "checks": [], "errors": []}
    with tempfile.TemporaryDirectory(prefix="pliac-student-ui-") as directory:
        with isolated_application(Path(directory)) as (base, _, _), sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get("PLIAC_BROWSER_CHANNEL") or None)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            page.on("pageerror", lambda e: report["errors"].append(str(e)))
            page.goto(base + "/app/")
            expect(page.get_by_role("heading", name="从上次停下的地方继续。")).to_be_visible()
            page.get_by_role("link", name="我的课程", exact=True).click()
            expect(page.get_by_role("heading", name="选择你的学习方向")).to_be_visible()
            report["checks"].append("Home and courses use real isolated API")
            page.goto(base + "/app/courses/ml_acceptance_demo")
            expect(page.locator(".lesson h1")).to_have_text("01 样本、特征与标签")
            page.get_by_role("button", name="切换教学对话").click()
            draft = page.get_by_role("textbox", name="当前课程的问题草稿")
            draft.fill("测试草稿：为什么要划分验证集？")
            for theme in ["neutral", "dark", "paper"]:
                page.get_by_label("外观主题").select_option(theme)
                expect(page.locator("html")).to_have_attribute("data-theme", theme)
                expect(draft).to_have_value("测试草稿：为什么要划分验证集？")
                contrasts = page.evaluate('''() => {
                    const style = getComputedStyle(document.documentElement);
                    function luminance(token) {
                        let hex = style.getPropertyValue(token).trim().slice(1);
                        if (hex.length === 3) hex = [...hex].map(x => x+x).join('');
                        const values = hex.match(/../g).map(x => parseInt(x,16)/255)
                            .map(x => x <= .04045 ? x/12.92 : ((x+.055)/1.055)**2.4);
                        return values[0]*.2126 + values[1]*.7152 + values[2]*.0722;
                    }
                    return ['--ink','--muted','--accent'].flatMap(foreground =>
                        ['--bg','--side','--surface','--hover'].map(background => {
                            const a=luminance(foreground), b=luminance(background);
                            return {foreground, background, ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
                        }));
                }''')
                assert all(item['ratio'] >= 4.5 for item in contrasts), (theme, contrasts)
            page.locator(".course-nav button").nth(1).click()
            title = page.locator(".lesson h1").inner_text()
            page.reload()
            expect(page.locator(".lesson h1")).to_have_text(title)
            page.get_by_role("button", name="切换教学对话").click()
            expect(page.get_by_role("textbox")).to_have_value("测试草稿：为什么要划分验证集？")
            report["checks"].append("Theme, selected node and unsent draft survive reload")
            report['checks'].append('Three themes: ink/muted/accent against bg/side/surface/hover meet project 4.5:1 token contrast target; not a full accessibility audit')
            page.screenshot(path=str(OUTPUT / "student-app-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.locator(".conversation")).to_be_visible()
            page.get_by_role("button", name="收起对话").click()
            if page.locator(".course-nav").is_visible():
                page.get_by_role("button", name="切换课程目录").click()
            expect(page.locator(".lesson h1")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Horizontal overflow"
            page.screenshot(path=str(OUTPUT / "student-app-mobile.png"), full_page=True)
            report["checks"].append("Mobile reading and dialog work without horizontal overflow")
            page.get_by_role("link", name="返回课程").click()
            page.get_by_role("button", name="打开导航").click()
            expect(page.get_by_role('button', name='关闭导航')).to_be_focused()
            expect(page.get_by_role('dialog', name='主导航')).to_be_visible()
            page.screenshot(path=str(OUTPUT / 'student-navigation-mobile.png'))
            page.locator('.main-page a').first.evaluate('element => element.focus()')
            expect(page.get_by_role('button', name='关闭导航')).to_be_focused()
            page.keyboard.press('Escape')
            expect(page.get_by_role('button', name='关闭导航')).not_to_be_visible()
            expect(page.get_by_role('button', name='打开导航')).to_be_focused()
            page.get_by_role('button', name='打开导航').click()
            page.set_viewport_size({'width': 1440, 'height': 960})
            expect(page.get_by_role('dialog', name='主导航')).to_have_count(0)
            expect(page.get_by_role('link', name='学习档案', exact=True)).to_be_visible()
            page.set_viewport_size({'width': 390, 'height': 844})
            page.get_by_role('button', name='打开导航').click()
            page.get_by_role("link", name="学习档案", exact=True).click()
            expect(page.get_by_role("heading", name="把理解留下来。")).to_be_visible()
            report["checks"].append("Mobile navigation focuses close, blocks background focus, restores opener on Escape, adapts to desktop and reaches archive")
            assert not report["errors"], report["errors"]
            browser.close()
    (OUTPUT / "student-app-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
