import pytest

from marginalia import config
from marginalia.store import Course


@pytest.fixture
def course(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "COURSES_DIR", tmp_path)
    course = Course("fixture")
    course.materials.mkdir(parents=True)
    return course
