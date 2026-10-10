"""Real-browser math, Markdown, isolation and mobile-layout checks."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application, ROOT
from pliac.tutor import TeachingProposal

CONTENT = r"""## 先理解损失函数

平均平方误差写为 \(L=\frac{1}{n}\sum_{i=1}^n(y_i-\hat y_i)^2\)。

\[\hat y = w_1x_1+w_2x_2+b\]

- 训练集用来拟合参数。
- 验证集用来选择模型。
- 测试集留到最后评价。

| 训练集 | 验证集 | 测试集 | 参数 | 超参数 | 误差 |
|---|---|---|---|---|---|
| 拟合 | 选择 | 评价 | 权重 | 深度 | 差异 |

```python
formula = r"\(do_not_change_code\)"
```

![不应请求外部图片](https://attacker.invalid/pixel.png)

[不可执行的链接](javascript:alert(1))

<img src="https://attacker.invalid/html.png" onerror="window.richTextAttack=true">

错误公式保留并提示：$\frac{$
"""


def main():
    async def model(context, config):
        source = context['sources'][0]
        return TeachingProposal(response="下面结合公式、表格和代码说明。", target_node_id=context["current_node_id"], action="explain",
            rationale="合成排版测试", question="哪些数据可以用于模型选择？", uncertainty="本内容仅用于排版核验。",
            blocks=[{"heading": "数据划分与模型评价", "text": CONTENT, "citations": [{"source_id": source['id'], "quote": source['text'][:15]}]}]), {"model": "synthetic"}

    with tempfile.TemporaryDirectory(prefix="rich-text-") as directory:
        with isolated_application(Path(directory)) as (base, _, _), patch("pliac.tutor_api.configured_api", return_value=object()), patch("pliac.tutor_api.generate_teaching", model), sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=os.environ.get("PLIAC_BROWSER_CHANNEL") or None)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors, requests = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append(request.url))
            page.goto(base + '/app/')
            expect(page.get_by_role('heading', name='从上次停下的地方继续。')).to_be_visible()
            assert not any('RichTextContent' in url for url in requests)
            page.goto(base + '/app/courses/ml_acceptance_demo')
            page.get_by_role('button', name='切换教学对话').click()
            page.get_by_role('textbox', name='当前课程的问题草稿').fill('合成排版测试')
            page.get_by_role('button', name='发送学习问题').click()
            page.get_by_role('link', name='在正文区阅读完整讲解').click()
            material = page.locator('.teaching-material')
            expect(material.locator('.katex')).to_have_count(2)
            expect(material.locator('.katex-error')).to_have_count(1)
            expect(material.locator('pre code')).to_have_text('formula = r"\\(do_not_change_code\\)"\n')
            expect(material.locator('.rich-text ol li')).to_have_count(3)
            expect(material.locator('.rich-text img')).to_have_count(0)
            expect(material.locator('.rich-text a')).to_have_count(0)
            assert page.evaluate('window.richTextAttack === undefined')
            assert not any('attacker.invalid' in url for url in requests), requests
            page.get_by_role('button', name='收起对话').click()
            output = ROOT / 'outputs' / 'verification'
            output.mkdir(parents=True, exist_ok=True)
            page.set_viewport_size({'width': 1440, 'height': 1800})
            material.screenshot(path=str(output / 'rich-text-desktop.png'))
            page.set_viewport_size({'width': 390, 'height': 844})
            if page.locator('.course-nav').is_visible():
                page.get_by_role('button', name='切换课程目录').click()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Page overflow'
            table = material.locator('.table-scroll')
            assert table.evaluate('(el) => el.scrollWidth > el.clientWidth'), 'Wide table should scroll locally'
            question = material.get_by_text('哪些数据可以用于模型选择？', exact=True)
            question.scroll_into_view_if_needed()
            expect(question).to_be_visible()
            page.set_viewport_size({'width': 390, 'height': 1800})
            material.screenshot(path=str(output / 'rich-text-mobile.png'))
            page.set_viewport_size({'width': 390, 'height': 844})
            for theme in ['dark', 'neutral', 'paper']:
                page.get_by_label('外观主题').select_option(theme)
                expect(material.locator('.katex')).to_have_count(2)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors
            browser.close()
            print('PASS lazy rendering, TeX delimiters, code preservation, table scroll, three themes, no active HTML/links or external media')


if __name__ == '__main__':
    main()
