from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from learning_agent.api import router, courses_router
from learning_agent.document_api import router as document_router
from learning_agent.documents import ocr_threads
from .api import router as learning_router
from .ml_api import router as ml_router
from .margin import router as margin_router, close_jobs
from .tutor_api import router as tutor_router
from .teaching_jobs import close_teaching_jobs
from .access import router as access_router, access_gate
from .media_api import router as media_router
from .media_cleanup import MediaCleanup

ROOT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def lifespan(app):
    from learning_agent import api as course_api
    cleanup = MediaCleanup(lambda: course_api.store.output_dir)
    app.state.media_cleanup = cleanup
    await cleanup.start()
    try:
        yield
    finally:
        await cleanup.close()
        await close_teaching_jobs()
        await close_jobs()

app = FastAPI(title="PLIAC · 课程个性化学习智能体", version="0.10.0", lifespan=lifespan)
app.middleware("http")(access_gate)
app.include_router(access_router)
app.include_router(media_router)
app.include_router(margin_router)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.include_router(router)
app.include_router(courses_router)
app.include_router(document_router)
app.include_router(learning_router)
app.include_router(ml_router)
app.include_router(tutor_router)


@app.get("/ml-lab")
def ml_lab():
    return FileResponse(ROOT / "static/ml-lab.html")


@app.get("/learn")
@app.get("/review")
def learning_workspace():
    return FileResponse(ROOT / "static/learning.html")


@app.get("/documents")
def documents():
    return FileResponse(ROOT / "static/documents.html")


@app.get("/courses")
@app.get("/manage/courses")
def courses():
    return FileResponse(ROOT / "static/courses.html")


@app.get("/")
def home():
    return RedirectResponse("/courses", status_code=307)


@app.get("/knowledge")
@app.get("/author")
@app.get("/admin")
def workbench():
    return FileResponse(ROOT / "static/index.html")


@app.get("/health")
def health():
    return {"app": "learning-agent", "platform": "PLIAC", "capabilities": ["knowledge_graph", "learning_workspace", "acceptance_course", "ml_lab", "course_home", "study_rhythm", "learnmargin_graph", "scoped_learning_units"],
            "version": app.version, "specification": "build-guide-20261009-v1.6", "student_entry": "/app/", "ocr_threads": ocr_threads()}


@app.get("/api/course-assets/training-blueprints")
def training_blueprints():
    """Teacher-side draft assets only; this endpoint does not run or grade training."""
    return FileResponse(ROOT / "data/training_blueprints.json", media_type="application/json")


@app.get("/api/course-assets/design-references")
def design_references():
    return FileResponse(ROOT / "data/design_references.json", media_type="application/json")


@app.get("/course-reader")
def margin_reader():
    return FileResponse(ROOT / "static/margin-reader.html")


@app.get("/app")
@app.get("/app/{frontend_path:path}")
def student_app(frontend_path: str = ""):
    """Serve the independent student app without intercepting legacy/API routes."""
    distribution = ROOT / "web/dist"
    if frontend_path.startswith("assets/"):
        target = (distribution / frontend_path).resolve()
        if not target.is_relative_to((distribution / "assets").resolve()) or not target.is_file():
            raise HTTPException(404, "前端资源不存在。")
        return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"})
    index = distribution / "index.html"
    if not index.is_file():
        raise HTTPException(503, "新工作台尚未构建，请先在 web 目录执行 npm install 和 npm run build。旧入口仍可使用。")
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
