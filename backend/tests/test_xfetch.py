"""Unit tests for the XFetch early-refresh decision (pure function)."""
import random

from app.cache.aside import should_refresh_early


def refresh_rate(seconds_left: float, compute_seconds: float = 0.05, beta: float = 1.0) -> float:
    rng = random.Random(0)
    now, expires_at = 1000.0, 1000.0 + seconds_left
    trials = 20_000
    hits = sum(should_refresh_early(now, expires_at, compute_seconds, beta, rng.random()) for _ in range(trials))
    return hits / trials


def test_far_from_expiry_almost_never_refreshes():
    assert refresh_rate(seconds_left=60) == 0.0


def test_refresh_gets_more_likely_as_expiry_approaches():
    assert refresh_rate(0.5) < refresh_rate(0.1) < refresh_rate(0.01)


def test_already_expired_always_refreshes():
    assert refresh_rate(seconds_left=0) == 1.0


def test_slower_queries_refresh_earlier():
    assert refresh_rate(0.2, compute_seconds=0.5) > refresh_rate(0.2, compute_seconds=0.01)


def test_higher_beta_refreshes_earlier():
    assert refresh_rate(0.2, beta=3.0) > refresh_rate(0.2, beta=0.5)


def test_random_zero_does_not_crash():
    assert should_refresh_early(0, 10, 0.1, 1.0, 0.0) in (True, False)
