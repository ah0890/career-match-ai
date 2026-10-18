import pytest
from pydantic import ValidationError

from config.settings import RecommendationThresholds, ScoringWeights, Settings


def _settings(**overrides) -> Settings:
    # _env_file=None isolates tests from any developer .env file.
    return Settings(_env_file=None, **overrides)


def test_default_weights_sum_to_100():
    weights = _settings().scoring_weights
    assert sum(weights.as_dict().values()) == pytest.approx(100)
    assert weights.required_skills == 25


def test_weights_not_summing_to_100_are_rejected():
    with pytest.raises(ValidationError, match="sum to 100"):
        ScoringWeights(ats=30)


def test_negative_weight_is_rejected():
    with pytest.raises(ValidationError):
        ScoringWeights(ats=-5, required_skills=50)


def test_invalid_weights_from_environment_fail_fast(monkeypatch):
    monkeypatch.setenv("CAREERMATCH_WEIGHT_ATS", "50")
    with pytest.raises(ValidationError, match="sum to 100"):
        _settings()


def test_default_thresholds():
    t = _settings().thresholds
    assert (t.apply, t.improve) == (80, 70)


def test_thresholds_must_be_ordered():
    with pytest.raises(ValidationError):
        RecommendationThresholds(apply=60, improve=75)


def test_threshold_out_of_range_rejected():
    with pytest.raises(ValidationError):
        RecommendationThresholds(apply=120)


def test_upload_limit_in_bytes(monkeypatch):
    monkeypatch.setenv("CAREERMATCH_MAX_UPLOAD_MB", "2")
    assert _settings().max_upload_bytes == 2 * 1024 * 1024


def test_upload_limit_must_be_positive():
    with pytest.raises(ValidationError):
        _settings(max_upload_mb=0)
