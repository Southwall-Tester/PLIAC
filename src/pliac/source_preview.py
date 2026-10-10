"""Course-scoped, saved-citation source preview, never arbitrary file access."""
import hashlib

from learning_agent.course_graph import CourseGraphError, safe_id


def source_reference(store, student, material_id, source_id):
    safe_id(student, '学习编号'); safe_id(material_id, '材料编号')
    learner = store._read_learner(student)
    turn = next((item for item in learner.get('workspace', {}).get('tutor_turns', []) if item['request_id'] == material_id), None)
    if not turn:
        raise CourseGraphError('未找到本人的学习材料。', 404)
    source = next((item for item in turn.get('source_catalog', []) if item['id'] == source_id), None)
    if not source or source.get('origin') != 'uploaded_document':
        raise CourseGraphError('该引用没有可预览的上传原文页。', 404)
    ident, page = source.get('document_id'), source.get('page')
    if not ident or type(page) is not int or page < 1:
        raise CourseGraphError('历史引用缺少资料页映射，仍可查看保存的引文。', 409)
    graph = store.load_graph()
    if not graph or not any(node.get('document_id') == ident and any(item.get('page') == page for item in node.get('document_evidence', [])) for node in graph['nodes']):
        raise CourseGraphError('该原文页当前未关联到可用课程，历史引文仍保留。', 403)
    return source


def source_preview(store, documents, student, material_id, source_id):
    source = source_reference(store, student, material_id, source_id)
    ident, page = source['document_id'], source['page']
    text = documents.page(ident, page).get('text', '')
    if not isinstance(text, str) or not text.strip():
        raise CourseGraphError('原文页尚无可读文本，请使用原文件或联系维护者。', 409)
    if len(text) > 200_000:
        raise CourseGraphError('原文页超过预览限制，请使用原文件。', 413)
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    return {'title': source.get('title', '原始资料'), 'page': page, 'text': text,
            'changed': digest != source.get('content_digest'), 'source_id': source_id,
            'notice': '这是当前解析的原文文本，不是 PDF 原版式；图片和复杂排版请查看原文件。'}


def source_page_image(store, documents, student, material_id, source_id):
    """Render only the authorized citation page, without active PDF content."""
    import fitz
    source = source_reference(store, student, material_id, source_id)
    path = documents.source(source['document_id'])
    if path.suffix.lower() != '.pdf':
        raise CourseGraphError('该资料不是 PDF，请使用文字预览或原文件。', 415)
    if not path.is_file():
        raise CourseGraphError('原文件不存在。', 404)
    try:
        with fitz.open(path) as pdf:
            if pdf.needs_pass or not 1 <= source['page'] <= len(pdf):
                raise CourseGraphError('原文件已变化或需要密码，无法显示该引用页。', 409)
            page = pdf[source['page'] - 1]
            longest = max(page.rect.width, page.rect.height)
            if longest <= 0:
                raise CourseGraphError('原文件页尺寸无效。', 409)
            scale = min(2, 2200 / longest)
            return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes('png')
    except CourseGraphError:
        raise
    except (RuntimeError, ValueError) as exc:
        raise CourseGraphError('PDF 页面无法显示，可尝试文字预览。', 409) from exc
