"""Real browser, synthetic model: persistent panel, context and editable profile."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
from playwright.sync_api import sync_playwright, expect
from test_ui_documents import isolated_application
from test_assistant import CONFIG, reply
from pliac import assistant
from build_linux_course import DEST, COURSE_ID
from install_course_draft import install


def main():
    output=ROOT/"outputs/verification/assistant"
    output.mkdir(parents=True,exist_ok=True)
    calls,errors=[],[]
    async def model(messages,context):
        calls.append(dict(messages=messages,context=context))
        await asyncio.sleep(.6)
        text=messages[-1]["content"]
        updates=[]
        if "先给结论" in text:
            updates=[dict(category="preference",slot="detail",value="先给结论，再举例",quote="先给结论",basis="explicit")]
        return reply("**先看结论**：这是合成模型的浏览器验收回答。\n\n- 第一步理解概念\n- 第二步换一个例子\n\n```bash\npwd\n```",
                     profile_updates=updates)
    with tempfile.TemporaryDirectory() as temp, patch.object(assistant,"configured_api",return_value=CONFIG), \
         patch.object(assistant.ChatProvider,"chat",side_effect=model), \
         isolated_application(Path(temp)) as (base,store,_), sync_playwright() as p:
        install(DEST/"course.json",store)
        browser=p.chromium.launch()
        page=browser.new_page(viewport={"width":1440,"height":1000})
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.goto(base+"/courses")
        panel=page.locator("pliac-assistant")
        expect(panel.locator(".panel")).to_be_visible()
        expect(panel.locator("#input")).to_be_visible()
        panel.locator("#input").fill("请先给结论，再举例讲解。")
        panel.locator("#send").click()
        expect(panel.locator("#stop")).to_be_visible()
        # Navigate while a reply is running: server job continues, browser restores it.
        page.goto(base+"/knowledge?course_id="+COURSE_ID)
        expect(panel.locator(".assistant .body")).to_contain_text("合成模型")
        panel.locator("#input").fill("暂存草稿")
        page.reload()
        expect(panel.locator("#input")).to_have_value("暂存草稿")
        panel.locator("#profileButton").click()
        expect(panel.locator(".profile-item")).to_contain_text("先给结论，再举例")
        panel.locator("[data-edit]").click()
        panel.locator(".profile-item textarea").fill("用步骤和短例子解释")
        panel.locator("[data-edit]").click()
        expect(panel.locator(".profile-item")).to_contain_text("你已修正")
        expect(panel.locator(".episode")).to_have_count(1)
        panel.locator("[data-episode-edit]").click()
        panel.locator(".episode textarea").fill("这次学习先用终端路径练习")
        panel.locator("[data-episode-edit]").click()
        expect(panel.locator(".episode")).to_contain_text("你已修正")
        page.screenshot(path=str(output/"profile-desktop.png"))
        panel.locator("#backChat").click()
        panel.locator("#input").fill("请解释 chmod")
        panel.locator("#send").click()
        expect(panel.locator(".assistant")).to_have_count(2)
        assert calls[-1]["context"]["personalization"]["preferences"][0]["value"]=="用步骤和短例子解释"
        assert calls[-1]["context"]["references"]
        page.screenshot(path=str(output/"chat-desktop.png"))
        panel.locator("#close").click()
        expect(panel.locator("#open")).to_be_visible()
        page.reload()
        expect(panel.locator("#open")).to_be_visible()
        page.set_viewport_size({"width":390,"height":844})
        panel.locator("#open").click()
        expect(panel.locator("#input")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(path=str(output/"chat-mobile.png"))
        panel.locator("#profileButton").click()
        panel.locator("[data-delete]").click()
        expect(panel.locator(".empty-profile")).to_be_visible()
        panel.locator("#backChat").click()
        panel.locator("#new").click()
        expect(panel.locator(".welcome")).to_be_visible()
        panel.locator("#close").click()
        page.locator("#themeButton").click()
        panel.locator("#open").click()
        expect(panel).to_have_attribute("dark","")
        page.screenshot(path=str(output/"empty-dark-mobile.png"))
        assert not errors,errors
        browser.close()
    result=dict(passed=True,model="synthetic",checks=["navigation during reply","history and draft restoration",
                "profile changes next request","profile correction and deletion","context references",
                "desktop/mobile","dark mode","collapse persists"],page_errors=errors)
    (output/"report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
