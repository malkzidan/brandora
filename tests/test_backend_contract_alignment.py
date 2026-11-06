"""Offline compatibility checks; no external service or provider."""
import pytest
from pydantic import ValidationError
from app.config import ConfigError
from app.offline_demo import OfflineHarness
from app.schemas.backend import ScopedHistoryMessage

def row(content):
    return dict(id="00000001-0000-4000-8000-000000000001",
        conversationId="00000002-0000-4000-8000-000000000001",
        senderType="CUSTOMER",messageType="TEXT",content=content,
        createdAt="2026-11-05T10:00:00.000Z")

@pytest.mark.parametrize("text", ["a" * 2000, "\u0628" * 2000, "\U0001f600" * 2000])
def test_history_accepts_exact_codepoint_boundary(text):
    assert ScopedHistoryMessage.model_validate(row(text)).content == text

@pytest.mark.parametrize("text", ["a" * 2001, "\u0628" * 2001, "\U0001f600" * 2001])
def test_history_rejects_oversize_without_truncation(text):
    with pytest.raises(ValidationError):
        ScopedHistoryMessage.model_validate(row(text))

@pytest.mark.parametrize("seconds", [0, -1, 25.01, 30, 60, float("inf"), float("nan")])
def test_canonical_budget_must_fit_backend_deadline(seconds):
    with pytest.raises(ConfigError):
        OfflineHarness(integration_timeout_seconds=seconds)

def test_canonical_budget_accepts_25_seconds():
    assert OfflineHarness(integration_timeout_seconds=25).settings.integration_timeout_seconds == 25
