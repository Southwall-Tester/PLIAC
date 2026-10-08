from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .document_api import router as document_router

ROOT = Path(__file__).resolve().parents[2]
app = FastAPI(title="课程个性化学习智能体 · 知识与诊断底座", version="0.4.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.include_router(router)
app.include_router(document_router)


@app.get("/documents")
def documents():
    return FileResponse(ROOT / "static/documents.html")


@app.get("/")
@app.get("/knowledge")
@app.get("/author")
@app.get("/admin")
def workbench():
    return FileResponse(ROOT / "static/index.html")


@app.get("/health")
def health():
    return {"app": "learning-agent", "version": "0.4.0", "specification": "v7_20261008"}


@app.get("/api/course-assets/training-blueprints")
def training_blueprints():
    """Teacher-side draft assets only; this endpoint does not run or grade training."""
    return FileResponse(ROOT / "data/training_blueprints.json", media_type="application/json")


@app.get("/api/course-assets/design-references")
def design_references():
    return FileResponse(ROOT / "data/design_references.json", media_type="application/json")
