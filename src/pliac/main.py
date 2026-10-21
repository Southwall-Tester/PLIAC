from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from learning_agent.api import router, courses_router
from learning_agent.document_api import router as document_router
from learning_agent.documents import ocr_threads
from .api import router as learning_router
from .ml_api import router as ml_router
from .linux_api import router as linux_router
from .margin import router as margin_router, close_jobs
from .assistant import router as assistant_router, close_chats
from .accounts import router as account_router, AccountMiddleware
from .journey import close_journeys
from .home import router as home_router
from . import VERSION

ROOT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def lifespan(app):
    yield
    await close_chats()
    await close_journeys()
    await close_jobs()

app = FastAPI(title="PLIAC · 课程个性化学习智能体", version=VERSION, lifespan=lifespan)
app.add_middleware(AccountMiddleware)
app.include_router(account_router)
app.include_router(margin_router)
app.mount("/static/math", StaticFiles(directory=ROOT / "src/learnmargin/assets/katex"), name="preview-math")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.include_router(router)
app.include_router(courses_router)
app.include_router(document_router)
app.include_router(learning_router)
app.include_router(ml_router)
app.include_router(linux_router)
app.include_router(assistant_router)
app.include_router(home_router)


@app.get("/login")
def login_page():
    return FileResponse(ROOT / "static/login.html")


@app.get("/linux-lab")
def linux_lab():
    return FileResponse(ROOT / "static/linux-lab.html")


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


@app.get("/manage/courses")
def courses():
    return FileResponse(ROOT / "static/courses.html")


@app.get("/")
@app.get("/courses")
@app.get("/preview")
def home():
    return FileResponse(ROOT / "static/home.html")


@app.get("/knowledge")
@app.get("/author")
@app.get("/admin")
def workbench():
    return FileResponse(ROOT / "static/index.html")


@app.get("/health")
def health():
    return {"app": "learning-agent", "platform": "PLIAC", "capabilities": ["knowledge_graph", "learning_workspace", "acceptance_course", "ml_lab", "linuxlab", "linuxlab_diagnostic_drafts", "linuxlab_dialogue_diagnostics", "course_home", "study_rhythm", "learnmargin_graph", "scoped_learning_units", "learning_assistant"],
            "version": app.version, "specification": "v7_20261008", "ocr_threads": ocr_threads()}


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
