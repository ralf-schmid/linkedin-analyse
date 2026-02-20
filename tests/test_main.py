"""
Tests für app/main.py – FastAPI-Endpunkte
"""

import base64
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.analyzer import Post, AnalysisConfig


client = TestClient(app)


def basic_auth_header(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def make_post(**kwargs) -> Post:
    defaults = dict(
        id="1",
        keyword="AI",
        author="Test User",
        author_title="Engineer",
        author_url="https://linkedin.com/in/test",
        text="Testpost",
        posted_at="2025-05-01T10:00:00Z",
        likes=10,
        comments=2,
        reposts=1,
        url="https://linkedin.com/posts/1",
        sentiment_post="positiv",
        sentiment_score=0.7,
        main_topics=["KI"],
        summary="Positiver Post.",
    )
    defaults.update(kwargs)
    return Post(**defaults)


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_200(self):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_returns_ok_status(self):
        resp = client.get("/health")
        assert resp.json()["status"] == "ok"

    def test_returns_time_field(self):
        resp = client.get("/health")
        assert "time" in resp.json()


# ── / (index) ─────────────────────────────────────────────────────────────────

class TestIndexEndpoint:
    def test_returns_200(self):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_returns_html(self):
        resp = client.get("/")
        assert "text/html" in resp.headers["content-type"]

    def test_contains_form(self):
        resp = client.get("/")
        assert "<form" in resp.text


# ── /analyze (sync) ───────────────────────────────────────────────────────────

class TestAnalyzeSyncEndpoint:
    def test_returns_html_report(self):
        mock_posts = [make_post()]
        mock_summary = "Zusammenfassung des Tests."

        with patch("app.main.LinkedInAnalyzer") as MockAnalyzer:
            instance = AsyncMock()
            instance.run.return_value = (mock_posts, mock_summary)
            MockAnalyzer.return_value = instance

            resp = client.post("/analyze", data={
                "keywords": "AI",
                "days": "7",
                "max_posts": "10",
                "include_comments": "true",
            })

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Test User" in resp.text

    def test_keywords_are_split_correctly(self):
        captured_config = {}

        async def fake_run():
            return [], "Summary"

        with patch("app.main.LinkedInAnalyzer") as MockAnalyzer:
            def capture(config):
                captured_config["keywords"] = config.keywords
                instance = AsyncMock()
                instance.run = fake_run
                return instance
            MockAnalyzer.side_effect = capture

            client.post("/analyze", data={
                "keywords": "AI, LLM, Claude",
                "days": "7",
                "max_posts": "10",
                "include_comments": "true",
            })

        assert captured_config["keywords"] == ["AI", "LLM", "Claude"]


# ── /analyze/stream (SSE) ─────────────────────────────────────────────────────

class TestAnalyzeStreamEndpoint:
    def _make_stream_events(self, posts, summary):
        """Erstellt einen async-Generator, der SSE-Events simuliert."""
        async def gen():
            yield {"type": "progress", "message": "Starte ...", "percent": 10}
            yield {
                "type": "done",
                "message": "Fertig.",
                "percent": 100,
                "posts": [p.to_dict() for p in posts],
                "summary": summary,
            }
        return gen()

    def test_stream_returns_200(self):
        with patch("app.main.LinkedInAnalyzer") as MockAnalyzer:
            instance = MagicMock()
            instance.run_stream.return_value = self._make_stream_events([], "Summary")
            MockAnalyzer.return_value = instance

            resp = client.post("/analyze/stream", data={
                "keywords": "AI",
                "days": "7",
                "max_posts": "10",
                "include_comments": "true",
            })

        assert resp.status_code == 200

    def test_stream_content_type_is_event_stream(self):
        with patch("app.main.LinkedInAnalyzer") as MockAnalyzer:
            instance = MagicMock()
            instance.run_stream.return_value = self._make_stream_events([], "Summary")
            MockAnalyzer.return_value = instance

            resp = client.post("/analyze/stream", data={
                "keywords": "AI",
                "days": "7",
                "max_posts": "10",
                "include_comments": "true",
            })

        assert "text/event-stream" in resp.headers["content-type"]

    def test_stream_done_event_contains_html(self):
        posts = [make_post()]
        with patch("app.main.LinkedInAnalyzer") as MockAnalyzer:
            instance = MagicMock()
            instance.run_stream.return_value = self._make_stream_events(posts, "Test Summary")
            MockAnalyzer.return_value = instance

            resp = client.post("/analyze/stream", data={
                "keywords": "AI",
                "days": "7",
                "max_posts": "10",
                "include_comments": "true",
            })

        # Parse SSE lines
        events = []
        for line in resp.text.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        assert "html" in done_events[0]
        assert "<!DOCTYPE html>" in done_events[0]["html"]


# ── HTTP Basic Auth ───────────────────────────────────────────────────────────

class TestHttpBasicAuth:
    """Auth-Tests laufen mit gepatchten Env-Variablen in app.main."""

    def test_no_auth_configured_allows_access(self):
        """Ohne WEB_USER/WEB_PASSWORD ist das Frontend offen erreichbar."""
        with patch("app.main._WEB_USER", ""), patch("app.main._WEB_PASSWORD", ""):
            resp = client.get("/")
        assert resp.status_code == 200

    def test_correct_credentials_grant_access(self):
        with patch("app.main._WEB_USER", "admin"), patch("app.main._WEB_PASSWORD", "geheim"):
            resp = client.get("/", headers=basic_auth_header("admin", "geheim"))
        assert resp.status_code == 200

    def test_wrong_password_returns_401(self):
        with patch("app.main._WEB_USER", "admin"), patch("app.main._WEB_PASSWORD", "geheim"):
            resp = client.get("/", headers=basic_auth_header("admin", "falsch"))
        assert resp.status_code == 401

    def test_wrong_username_returns_401(self):
        with patch("app.main._WEB_USER", "admin"), patch("app.main._WEB_PASSWORD", "geheim"):
            resp = client.get("/", headers=basic_auth_header("root", "geheim"))
        assert resp.status_code == 401

    def test_missing_credentials_returns_401(self):
        with patch("app.main._WEB_USER", "admin"), patch("app.main._WEB_PASSWORD", "geheim"):
            resp = client.get("/")  # kein Auth-Header
        assert resp.status_code == 401

    def test_401_response_contains_www_authenticate_header(self):
        with patch("app.main._WEB_USER", "admin"), patch("app.main._WEB_PASSWORD", "geheim"):
            resp = client.get("/")
        assert "WWW-Authenticate" in resp.headers
        assert 'Basic realm="LinkedIn Analyzer"' in resp.headers["WWW-Authenticate"]

    def test_health_endpoint_always_open(self):
        """Der /health-Endpunkt muss ohne Auth erreichbar sein (Docker Healthcheck)."""
        with patch("app.main._WEB_USER", "admin"), patch("app.main._WEB_PASSWORD", "geheim"):
            resp = client.get("/health")
        assert resp.status_code == 200

    def test_analyze_endpoint_protected(self):
        with patch("app.main._WEB_USER", "admin"), patch("app.main._WEB_PASSWORD", "geheim"):
            resp = client.post("/analyze", data={
                "keywords": "AI", "days": "7", "max_posts": "10", "include_comments": "true",
            })
        assert resp.status_code == 401

    def test_analyze_stream_endpoint_protected(self):
        with patch("app.main._WEB_USER", "admin"), patch("app.main._WEB_PASSWORD", "geheim"):
            resp = client.post("/analyze/stream", data={
                "keywords": "AI", "days": "7", "max_posts": "10", "include_comments": "true",
            })
        assert resp.status_code == 401
