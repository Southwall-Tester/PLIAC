"""Read-only exports of saved learner artifacts, without model regeneration."""
import copy
import threading
from html import escape

from playwright.async_api import async_playwright, Error as BrowserError

from learning_agent.course_graph import CourseGraphError, safe_id
from learnmargin.rendering import markdown, _math_assets

# Process-local capacity: reject excess work instead of accumulating browser jobs.
_PDF_SLOTS = threading.BoundedSemaphore(2)


def saved_snapshot(store, student_id, kind, ident):
    student_id = safe_id(student_id, "学习编号")
    ident = safe_id(ident, "材料编号")
    if kind not in {"material", "report", "textbook"}:
        raise CourseGraphError("仅支持已保存的个人材料与阶段报告。", 400)
    workspace = store._read_learner(student_id).get("workspace", {})
    key, field = ("tutor_turns", "request_id") if kind == "material" else ("stage_reports", "id")
    record = next((item for item in workspace.get(key, []) if item.get(field) == ident), None)
    if record is None:
        raise CourseGraphError("未找到当前学习档案中的材料。", 404)
    if kind == 'textbook':
        turns = {turn['request_id']: turn for turn in workspace.get('tutor_turns', [])}
        materials = []
        for ref in dict.fromkeys(record.get('material_ids', [])):
            if ref not in turns:
                raise CourseGraphError('历史教材引用缺失，无法生成完整汇编；阶段报告仍可查看。', 409)
            turn = turns[ref]
            materials.append({key: copy.deepcopy(turn[key]) for key in
                ('request_id', 'created_at', 'course_version', 'proposal', 'source_catalog', 'resource_catalog', 'activity')
                if key in turn})
        return {'report': copy.deepcopy(record), 'materials': materials}
    return copy.deepcopy(record)


def export_body(kind, record):
    """Whitelist visible content; never serialize provider metadata or task keys."""
    parts = []

    def text(value):
        parts.append('<p class="literal">' + escape(str(value or "")) + '</p>')

    def heading(value, level=2):
        parts.append(f'<h{level}>' + escape(str(value)) + f'</h{level}>')

    if kind == 'textbook':
        report = record['report']
        heading(report['title'] + ' · 个人教材汇编', 1)
        text(f"保存时间 {report['created_at']} · 汇编依据阶段报告 {report['id']}")
        text(report['goals'])
        text('只汇集本阶段已保存的讲解与笔记，不生成新知识，也不代表完整课程教材或掌握证明。不同讲解保留各自课程版本，后来的学习不会自动加入本汇编。')
        heading('目录')
        for index, material in enumerate(record['materials'], 1):
            blocks = material['proposal']['blocks']
            title = blocks[0]['heading'] if blocks else '教学安排'
            text(f'{index}. {title} · 课程 v{material["course_version"]}')
        if not record['materials']:
            text('这一阶段尚未保存智能体讲解；以下保留阶段笔记及学习记录。')
        for index, material in enumerate(record['materials'], 1):
            heading(f'{index} 已保存讲解')
            parts.append(export_body('material', material).replace('<h1>', '<h2>').replace('</h1>', '</h2>'))
        heading('附录：阶段笔记与学习记录')
        parts.append(export_body('report', report).replace('<h1>', '<h2>').replace('</h1>', '</h2>'))
    elif kind == "material":
        proposal = record["proposal"]
        heading(proposal["blocks"][0]["heading"] if proposal["blocks"] else "个人学习材料", 1)
        text(f'课程版本 {record["course_version"]} · 保存时间 {record["created_at"]}')
        parts.append(str(markdown(proposal["response"])))
        catalog = {source["id"]: source for source in record.get("source_catalog", [])}
        for index, block in enumerate(proposal["blocks"], 1):
            heading(f'{index} {block["heading"]}')
            parts.append(str(markdown(block["text"])))
            for number, citation in enumerate(block.get("citations", []), 1):
                source = catalog.get(citation["source_id"], {})
                location = f'，第 {source["page"]} 页' if source.get("page") else ""
                label = f'依据 {index}.{number}：{source.get("title", citation["source_id"])}{location}'
                parts.append('<p class="source-label">' + escape(label) + '</p>')
                text(citation["quote"])
        recommendations = proposal.get('recommended_resources', [])
        if recommendations:
            heading('建议的学习材料')
            resources = {item['id']: item for item in record.get('resource_catalog', [])}
            for index, recommendation in enumerate(recommendations, 1):
                resource = resources.get(recommendation['resource_id'], {})
                text(f"{index}. {resource.get('title', '历史推荐材料')} · {resource.get('applicable_segment', '')}")
                segment = resource.get('video_segment')
                if segment:
                    text(f"当时推荐片段：{segment['start_seconds']}—{segment['end_seconds']} 秒。")
                text(recommendation['reason'])
            text('这是当时保存的推荐说明，不代表已经阅读或掌握；材料当前是否可用请返回课程核对。')
        if proposal.get("question"):
            heading("继续思考")
            parts.append(str(markdown(proposal["question"])))
        heading("教学安排与边界")
        text(proposal.get("rationale"))
        text(proposal.get("uncertainty"))
        if record.get("activity", {}).get("notice"):
            text(record["activity"]["notice"])
        text("本文件保留已保存的讲解与来源，不重新生成内容。练习和实验须返回平台完成，阅读材料不代表已经掌握。")
    else:
        heading(record["title"], 1)
        text(f'课程版本 {record["course_version"]} · 保存时间 {record["created_at"]}')
        heading("1 学习目标与范围")
        text(record["goals"] or "尚未填写学习目标。")
        text(record["scope"])
        heading("2 知识点与证据记录")
        resolved = {ref for item in record["diagnoses"] for ref in (item.get("resolves_diagnosis_ids") or [])}
        labels = {"mastered": "有证据支持掌握", "needs_review": "需要复习或补学", "uncertain": "仍需核验", "unknown": "尚未核验"}
        for index, (ident, node) in enumerate(record["nodes"].items(), 1):
            heading(f'2.{index} {node["title"]}', 3)
            text(labels.get(node["status"], node["status"]))
            text(node["reason"])
            for item in record["evidence"]:
                if item["node_id"] != ident:
                    continue
                origin = "工具观察" if item.get("origin") == "system_observation" else "学习者记录"
                help_used = "记录了帮助使用" if item.get("prompt_level") else "未记录帮助使用"
                text(f'证据 {item["id"]} · {origin} · {help_used}')
                text(item["text"])
            for item in record["diagnoses"]:
                if item["node_id"] == ident:
                    text(f'历史诊断 {item["id"]}：{item["basis"]}')
                    if item.get("applicable") is False:
                        text("报告保存时知识内容版本已变化，此诊断仅供历史回看，不参与当时的掌握或冲突判断；这不代表旧问题已解决。")
                    if item["id"] in resolved:
                        text("这条历史问题在报告保存前已由后续独立核验覆盖，原记录保留。")
                    text("对应证据：" + "、".join(item.get("evidence_ids", [])))
        heading("3 当时保存的笔记")
        for index, note in enumerate(record["notes"], 1):
            heading(f'3.{index} {record["nodes"].get(note["node_id"], {}).get("title", note["node_id"])}', 3)
            text(note["text"])
        if not record["notes"]:
            text("保存报告时没有非空笔记。")
        heading("4 报告边界")
        text(record["limitations"])
        text("这是保存时的历史快照，不会随之后的学习更新。证据数量不是掌握比例。")
    body = "\n".join(parts)
    if 'class="image-description"' in body:
        body += '<p>图片在此文件中仅保留说明文字；原图与交互内容请返回平台查看。</p>'
    if len(body) > 500_000:
        raise CourseGraphError("材料较长，暂无法一次导出，请按学习阶段分别保存。", 422)
    return body


async def render_pdf(kind, record):
    if not _PDF_SLOTS.acquire(blocking=False):
        raise CourseGraphError('当前导出较多，请稍后手动重试；已保存材料不受影响。', 429)
    try:
        return await _render_pdf(kind, record)
    finally:
        _PDF_SLOTS.release()


async def _render_pdf(kind, record):
    body = export_body(kind, record)
    css, script = _math_assets()
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; font-src data:; script-src 'none'">
    <style>''' + css + '''
    @page {size:A4; margin:20mm 20mm 20mm 20mm}
    * {box-sizing:border-box; color:#000!important}
    body {width:170mm; margin:0; font:12pt/1.65 SimSun,"宋体",serif; overflow-wrap:anywhere}
    h1,h2,h3,h4,h5,h6 {font-family:STZhongsong,"华文中宋",serif; break-after:avoid; line-height:1.4}
    h1 {font-size:20pt} h2 {font-size:15pt; margin:18pt 0 7pt} h3 {font-size:13pt}
    p {margin:6pt 0; orphans:3; widows:3} .literal {white-space:pre-wrap}
    .source-label {break-after:avoid}
    table {border-collapse:collapse; width:100%; table-layout:fixed; margin:10pt 0}
    th,td {border:1px solid #000; padding:6pt; overflow-wrap:anywhere}
    thead {display:table-header-group} tr {break-inside:avoid}
    ul {list-style-type:decimal} pre {white-space:pre-wrap; overflow-wrap:anywhere}
    blockquote {margin:10pt 0 10pt 14pt} .katex-display {margin:10pt 0}
    </style><body>''' + body + '</body></html>'
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, chromium_sandbox=True)
            try:
                page = await browser.new_page(viewport={"width": 900, "height": 1100})
                await page.route("**/*", lambda route: route.abort())
                await page.set_content(html)
                # Only bundled code is evaluated; user strings remain DOM text/data.
                await page.evaluate(script)
                errors = await page.evaluate('''() => {
                    const errors = [];
                    for (const el of document.querySelectorAll('.math')) {
                        try { katex.render(el.dataset.tex, el, {displayMode: el.dataset.display === 'true', throwOnError:true, trust:false, maxExpand:1000}); }
                        catch (_) { errors.push('math'); }
                    }
                    for (const table of document.querySelectorAll('table')) {
                        const rows = [...table.querySelectorAll('tr')];
                        if (rows.length > 1 && rows.every(row => row.cells.length === 2) &&
                            rows.every(row => row.cells[0].textContent.length <= 8) &&
                            rows.slice(1).some(row => row.cells[1].textContent.length > 18)) {
                            const columns = document.createElement('colgroup');
                            const first = document.createElement('col'); first.style.width = '18%';
                            columns.append(first, document.createElement('col')); table.prepend(columns);
                        }
                    }
                    return errors;
                }''')
                await page.evaluate("document.fonts.ready")
                overflow = await page.evaluate('''() => {
                    const edge = document.body.getBoundingClientRect().right;
                    return [...document.querySelectorAll('p,pre,table,.math')].some(el =>
                        el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).display !== 'inline' ||
                        el.getBoundingClientRect().right > edge + 2);
                }''')
                if errors or overflow:
                    raise CourseGraphError("材料存在无法排版的公式或超宽内容，未导出；原始材料仍保留。", 422)
                return await page.pdf(format="A4", prefer_css_page_size=True, print_background=True)
            finally:
                await browser.close()
    except BrowserError as exc:
        raise CourseGraphError("PDF 渲染暂不可用，原始材料仍保留，请稍后重试。", 503) from exc
