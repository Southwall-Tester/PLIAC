"""Synthetic response fixtures for chat scroll behavior; no model or real learner."""
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application


def main():
    with tempfile.TemporaryDirectory(prefix="pliac-chat-scroll-") as folder:
        with isolated_application(Path(folder)) as (base, _, _), sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            errors, pending = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("localStorage.setItem('pliac.local-learner','synthetic-scroll')")
            response = page.request.get(base + "/api/learning?course_id=ml_acceptance_demo&student_id=synthetic-scroll")
            assert response.ok, response.text()
            state = response.json()
            node = state["course"]["nodes"][0]["id"]

            def turn(ident, message):
                return {"request_id": ident, "node_id": node, "message": message,
                        "created_at": "2026-10-10T00:00:00Z", "proposal": {
                            "target_node_id": node, "response": "合成历史讲解。" * 35,
                            "blocks": [], "action": "explain", "rationale": "仅验证界面滚动",
                            "question": "", "uncertainty": "不是教学效果证明"}}

            state["workspace"]["tutor_turns"] = [turn(f"history-{i}", f"历史问题 {i}") for i in range(20)]
            page.route("**/api/learning?*", lambda route: route.fulfill(json=state))
            page.route("**/api/tutor/reply?*", lambda route: pending.append(route))

            def deliver():
                page.wait_for_timeout(100)
                assert len(pending) == 1
                route = pending.pop()
                body = route.request.post_data_json
                record = turn(body["request_id"], body["message"])
                state["workspace"]["tutor_turns"].append(record)
                state["learner"]["version"] += 1
                route.fulfill(json={"turn": record, "state": state})

            page.goto(base + "/app/courses/ml_acceptance_demo")
            page.get_by_role("button", name="切换教学对话").click()
            history = page.get_by_role("region", name="教学对话记录")
            draft = page.get_by_role("textbox", name="当前课程的问题草稿")
            bottom = "e => e.scrollHeight-e.clientHeight-e.scrollTop"
            expect(page.locator(".tutor-turn")).to_have_count(20)
            page.wait_for_function("(() => {const e=document.querySelector('.conversation-history');return e.scrollHeight-e.clientHeight-e.scrollTop < 3})()")
            history.evaluate("e => e.scrollTop=400")
            page.wait_for_timeout(100)
            draft.fill("回看期间的新问题")
            page.get_by_role("button", name="发送学习问题").click()
            before = history.evaluate("e => e.scrollTop")
            deliver()
            expect(page.get_by_role("button", name="查看最新回复")).to_be_visible()
            expect(page.locator(".new-replies")).to_contain_text("有 1 条新回复")
            assert abs(history.evaluate("e => e.scrollTop") - before) < 3
            page.get_by_role("button", name="查看最新回复").click()
            expect(history).to_be_focused()
            expect(page.locator(".new-replies")).to_have_count(0)
            assert history.evaluate(bottom) < 3

            draft.fill("在末尾接收回复")
            page.get_by_role("button", name="发送学习问题").click()
            deliver()
            expect(page.locator(".tutor-turn")).to_have_count(22)
            page.wait_for_function("(() => {const e=document.querySelector('.conversation-history');return e.scrollHeight-e.clientHeight-e.scrollTop < 3})()")
            expect(page.locator(".new-replies")).to_have_count(0)

            history.evaluate("e => e.scrollTop=500")
            page.wait_for_timeout(100)
            draft.fill("收起期间的新回复")
            page.get_by_role("button", name="发送学习问题").click()
            before = history.evaluate("e => e.scrollTop")
            page.get_by_role("button", name="收起对话").click()
            deliver()
            expect(page.locator(".tutor-turn")).to_have_count(23)
            page.get_by_role("button", name="切换教学对话").click()
            expect(page.locator(".new-replies")).to_contain_text("有 1 条新回复")
            assert abs(history.evaluate("e => e.scrollTop") - before) < 3
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
            browser.close()
    print("PASS: follows latest; preserves history reading on reply; explicit unread jump; hidden replies preserve position; mobile width")


if __name__ == "__main__":
    main()
