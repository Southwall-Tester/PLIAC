from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from learning_agent.api import router, courses_router
from learning_agent.document_api import router as document_router
from learning_agent.documents import ocr_threads
from .api import router as learning_router
from .ml_api import router as ml_router

ROOT = Path(__file__).resolve().parents[2]
app = FastAPI(title="PLIAC · 课程个性化学习智能体", version="0.8.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.include_router(router)
app.include_router(courses_router)
app.include_router(document_router)
app.include_router(learning_router)
app.include_router(ml_router)


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
    return RedirectResponse("/learn?course_id=ml_acceptance_demo", status_code=307)


@app.get("/knowledge")
@app.get("/author")
@app.get("/admin")
def workbench():
    return FileResponse(ROOT / "static/index.html")


@app.get("/health")
def health():
    return {"app": "learning-agent", "platform": "PLIAC", "capabilities": ["knowledge_graph", "learning_workspace", "acceptance_course", "ml_lab", "course_home"],
            "version": app.version, "specification": "v7_20261008", "ocr_threads": ocr_threads()}


@app.get("/api/course-assets/training-blueprints")
def training_blueprints():
    """Teacher-side draft assets only; this endpoint does not run or grade training."""
    return FileResponse(ROOT / "data/training_blueprints.json", media_type="application/json")


@app.get("/api/course-assets/design-references")
def design_references():
    return FileResponse(ROOT / "data/design_references.json", media_type="application/json")
