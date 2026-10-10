"""Legacy import compatibility for the immutable v1 acceptance release."""
from .course_package import PACKAGES, PackagedCourseStore, read

DEMO_ID = "ml_acceptance_demo"
NOTICE = ""


def build_graph():
    return read(PACKAGES / DEMO_ID / "course.json")


class AcceptanceCourseStore(PackagedCourseStore):
    def __init__(self, default_store):
        super().__init__(default_store, PACKAGES / DEMO_ID / "package.json")
