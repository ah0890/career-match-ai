"""Saved CV versions (temporary database per test)."""

from datetime import datetime, timezone

import pytest

from config.settings import get_settings
from src.cv.extraction import ExtractionResult
from src.cv.session import ActiveCV
from src.cv.versions import (
    MAX_VERSIONS, VersionError, as_active_cv, compare_versions, delete_all, delete_version, find_by_sha,
    list_versions, rename_version, save_version,
)
from src.db.engine import session_scope
from tests.fixtures.match_factory import QUALITY_CV


@pytest.fixture
def db():
    return get_settings().database_url


def _cv(text=QUALITY_CV, sha="a" * 64, needs_ocr=False):
    return ActiveCV("cv.pdf", 2048, sha, datetime.now(timezone.utc),
                    ExtractionResult(text, "pdf", 1, needs_ocr=needs_ocr))


def test_save_stores_text_and_snapshot_only(db):
    with session_scope(db) as s:
        v = save_version(s, _cv(), "  Quality   roles ", "Manufacturing")
    with session_scope(db) as s:
        [saved] = list_versions(s)
        assert saved.name == "Quality roles" and saved.purpose == "Manufacturing"
        assert saved.text == QUALITY_CV and saved.ats_score is not None and saved.kind == "pdf"
        assert find_by_sha(s, "a" * 64).id == v.id


@pytest.mark.parametrize("kwargs, message", [
    ({"name": " "}, "at least 2 characters"),
    ({"cv": "ocr"}, "could not be read"),
])
def test_invalid_saves_are_rejected(db, kwargs, message):
    cv = _cv(text="", needs_ocr=True) if kwargs.get("cv") == "ocr" else _cv()
    with session_scope(db) as s, pytest.raises(VersionError, match=message):
        save_version(s, cv, kwargs.get("name", "Name"))


def test_duplicates_and_limit(db):
    with session_scope(db) as s:
        save_version(s, _cv(), "One")
        with pytest.raises(VersionError, match="already saved"):
            save_version(s, _cv(), "Other name")
        with pytest.raises(VersionError, match="already exists"):
            save_version(s, _cv(sha="b" * 64), "One")
        for i in range(MAX_VERSIONS - 1):
            save_version(s, _cv(text=QUALITY_CV + f"\nExtra {i}", sha=f"{i:064d}"), f"V{i}")
        with pytest.raises(VersionError, match=f"up to {MAX_VERSIONS}"):
            save_version(s, _cv(sha="c" * 64), "Too many")


def test_rename_delete_and_delete_all(db):
    with session_scope(db) as s:
        a = save_version(s, _cv(), "Alpha").id
        b = save_version(s, _cv(sha="b" * 64), "Beta").id
    with session_scope(db) as s:
        with pytest.raises(VersionError, match="already exists"):
            rename_version(s, b, "Alpha", None)
        rename_version(s, b, "Management", "Lead roles")
        delete_version(s, a)
    with session_scope(db) as s:
        assert [v.name for v in list_versions(s)] == ["Management"]
        assert delete_all(s) == 1 and list_versions(s) == []
        with pytest.raises(VersionError):
            delete_version(s, a)


def test_loaded_version_becomes_a_usable_active_cv(db):
    with session_scope(db) as s:
        v = save_version(s, _cv(), "Quality")
    active = as_active_cv(v)
    assert active.sha256 == "a" * 64 and active.extraction.text == QUALITY_CV
    assert active.filename == "Quality (cv.pdf)" and active.extraction.is_usable


def test_compare_versions_reports_skills_sections_ats_and_diff(db):
    improved = QUALITY_CV.replace("SKILLS\nSix Sigma, ISO 9001, FMEA, SPC, Python, SQL, Minitab",
                                  "SKILLS\nSix Sigma, ISO 9001, FMEA, SPC, Python, SQL, Minitab, Tableau, Kubernetes\n\n"
                                  "CERTIFICATIONS\nCertified Quality Engineer")
    with session_scope(db) as s:
        a = save_version(s, _cv(), "Original")
        b = save_version(s, _cv(text=improved, sha="b" * 64), "Improved")
    cmp = compare_versions(a, b)
    assert cmp.skills_added == ("Kubernetes", "Tableau") and cmp.skills_removed == ()
    assert cmp.sections_added == ("certifications",)
    assert cmp.words_after > cmp.words_before
    assert any(line.startswith("+CERTIFICATIONS") for line in cmp.diff)
    assert len(cmp.components) == 6
    same = compare_versions(a, a)
    assert same.diff == () and same.ats_before == same.ats_after
