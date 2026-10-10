"""Legacy import compatibility; all course behavior lives in the shared store."""
from .course_package import PACKAGES, PackagedCourseStore, read

DEMO_ID = "computer_organization_demo"
ASSETS = PACKAGES / DEMO_ID


def manifest():
    return read(ASSETS / "manifest.json")


class TextbookDemoStore(PackagedCourseStore):
    def __init__(self, default_store):
        super().__init__(default_store, ASSETS / "package.json")
