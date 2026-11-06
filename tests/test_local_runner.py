from dataclasses import replace
from types import SimpleNamespace
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from app.config import Settings
from app.local import create_local_application
from app.products_api import validate_canonical_result
from app.schemas.response import AiResponse


@pytest.fixture
def local(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    settings = Settings(
        ai_provider="rules", app_env="local", ai_integration_enabled=True,
        ai_service_token="synthetic-outbound-credential-32-characters",
        backend_service_token="synthetic-inbound-credential-32-characters",
        backend_base_url="http://127.0.0.1:3099", backend_context_public_key=public)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("AI_LOCAL_ENABLED", "true")
    monkeypatch.setenv("AI_LOCAL_PROVIDER", "rules")
    for name in ("RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_ENVIRONMENT_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("app.config.load_settings", lambda: settings)
    return settings


@pytest.mark.parametrize("name,value", [
    ("AI_LOCAL_ENABLED", "false"), ("APP_ENV", "production"), ("APP_ENV", "staging"),
    ("RAILWAY_SERVICE_ID", "deployed"), ("RAILWAY_PROJECT_ID", "deployed"),
    ("RAILWAY_ENVIRONMENT_ID", "deployed")])
def test_environment_gates(local, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        create_local_application()


@pytest.mark.parametrize("patch", [
    {"backend_base_url": "https://production.example"},
    {"backend_base_url": "http://127.0.0.1:3099/path"},
    {"integration_timeout_seconds": 30}, {"integration_timeout_seconds": 0},
    {"ai_integration_enabled": False},
    {"ai_service_token": "unsafe token with spaces long enough 123456"}])
def test_configuration_gates(local, monkeypatch, patch):
    monkeypatch.setattr("app.config.load_settings", lambda: replace(local, **patch))
    with pytest.raises(ValueError):
        create_local_application()


def test_rules_mode_has_no_legacy_routes(local):
    app = create_local_application()
    assert app.state.local_provider_mode == "rules"
    paths = set(app.openapi()["paths"])
    assert "/v2/ai/respond" in paths
    assert not paths & {"/v1/ai/respond", "/v2/ai/respond-with-context", "/v2/ai/products/respond"}
    response = TestClient(app).get("/ready")
    assert response.headers["X-AI-Local-Mode"] == "rules"
    assert response.json()["backendLiveVerified"] is False


def test_groq_requires_private_key_configuration(local, monkeypatch):
    monkeypatch.setenv("AI_LOCAL_PROVIDER", "groq")
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        create_local_application()


@pytest.mark.parametrize("reply", [" ", "x" * 20001, "\U0001f9f5" * 20000])
def test_canonical_output_bounds(reply):
    result = AiResponse(intent="INQUIRY", reply=reply, requiresReview=False, orderCandidate=None)
    with pytest.raises(ValueError):
        validate_canonical_result(result)


def test_canonical_ascii_boundary():
    result = AiResponse(intent="INQUIRY", reply="x" * 20000, requiresReview=False, orderCandidate=None)
    assert validate_canonical_result(result) is result
    assert set(result.model_dump()) == {"intent", "reply", "requiresReview", "orderCandidate"}


def test_oversized_canonical_response_returns_sanitized_503(monkeypatch):
    from app.offline_demo import OfflineHarness
    harness = OfflineHarness()
    async def oversized(*args):
        return SimpleNamespace(response=AiResponse(
            intent="INQUIRY", reply="x" * 20001, requiresReview=False, orderCandidate=None)), "not_requested"
    monkeypatch.setattr("app.products_api.execute_conversation", oversized)
    response = harness.send(harness.body("price"))
    assert response.status_code == 503
    assert response.json() == {"detail": "AI response unavailable"}


def test_egyptian_availability_word_is_not_a_product_qualifier():
    from app.data.search import canonical_search
    assert canonical_search("\u0639\u0646\u062f\u0643\u0648\u0627 \u062a\u064a\u0634\u064a\u0631\u062a \u0623\u0633\u0648\u062f\u061f") == "\u062a\u064a\u0634\u064a\u0631\u062a"
