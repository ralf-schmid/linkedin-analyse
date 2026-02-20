"""
Tests für app/report.py – HTML-Escape, Badges, Score-Bar und Report-Generierung
"""

import pytest
from app.report import _esc, _sentiment_badge, _score_bar, _format_date, build_report
from app.analyzer import AnalysisConfig, Post


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
        main_topics=["KI", "Tech"],
        summary="Ein positiver Testpost.",
    )
    defaults.update(kwargs)
    return Post(**defaults)


# ── _esc ──────────────────────────────────────────────────────────────────────

class TestEsc:
    def test_escapes_ampersand(self):
        assert _esc("A & B") == "A &amp; B"

    def test_escapes_less_than(self):
        assert _esc("<script>") == "&lt;script&gt;"

    def test_escapes_quotes(self):
        assert _esc('"hello"') == "&quot;hello&quot;"

    def test_escapes_single_quote(self):
        assert _esc("it's") == "it&#39;s"

    def test_none_returns_empty_string(self):
        assert _esc(None) == ""

    def test_plain_text_unchanged(self):
        assert _esc("Hello World") == "Hello World"


# ── _sentiment_badge ──────────────────────────────────────────────────────────

class TestSentimentBadge:
    def test_positiv_badge_contains_color(self):
        html = _sentiment_badge("positiv")
        assert "#16a34a" in html
        assert "positiv" in html

    def test_negativ_badge(self):
        html = _sentiment_badge("negativ")
        assert "#dc2626" in html

    def test_neutral_badge(self):
        html = _sentiment_badge("neutral")
        assert "neutral" in html

    def test_unknown_sentiment_renders_without_error(self):
        html = _sentiment_badge("unbekannt")
        assert "unbekannt" in html

    def test_badge_is_span_element(self):
        html = _sentiment_badge("positiv")
        assert html.startswith('<span')
        assert html.endswith('</span>')


# ── _score_bar ────────────────────────────────────────────────────────────────

class TestScoreBar:
    def test_positive_score_green(self):
        html = _score_bar(0.5)
        assert "#16a34a" in html

    def test_negative_score_red(self):
        html = _score_bar(-0.5)
        assert "#dc2626" in html

    def test_neutral_score_gray(self):
        html = _score_bar(0.0)
        assert "#6b7280" in html

    def test_score_displays_two_decimal_places(self):
        html = _score_bar(0.75)
        assert "0.75" in html

    def test_max_score_100_percent(self):
        html = _score_bar(1.0)
        assert "width:100%" in html

    def test_min_score_0_percent(self):
        html = _score_bar(-1.0)
        assert "width:0%" in html


# ── _format_date ──────────────────────────────────────────────────────────────

class TestFormatDate:
    def test_iso_date_formatted(self):
        assert _format_date("2025-05-01T10:00:00Z") == "01.05.2025"

    def test_invalid_date_returned_as_is(self):
        result = _format_date("not-a-date")
        assert result == "not-a-date"

    def test_empty_string_returns_dash(self):
        assert _format_date("") == "–"


# ── build_report ──────────────────────────────────────────────────────────────

class TestBuildReport:
    def test_returns_html_string(self):
        cfg = AnalysisConfig(keywords=["AI"])
        posts = [make_post()]
        html = build_report(posts, "Executive Summary.", cfg)
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_keyword_in_title(self):
        cfg = AnalysisConfig(keywords=["Agentic AI"])
        posts = [make_post()]
        html = build_report(posts, "Summary", cfg)
        assert "Agentic AI" in html

    def test_contains_post_author(self):
        cfg = AnalysisConfig(keywords=["AI"])
        posts = [make_post(author="Maria Muster")]
        html = build_report(posts, "Summary", cfg)
        assert "Maria Muster" in html

    def test_contains_summary(self):
        cfg = AnalysisConfig(keywords=["AI"])
        posts = [make_post()]
        html = build_report(posts, "Wichtige Executive Summary hier.", cfg)
        assert "Wichtige Executive Summary hier." in html

    def test_xss_in_author_escaped(self):
        cfg = AnalysisConfig(keywords=["AI"])
        posts = [make_post(author='<script>alert("xss")</script>')]
        html = build_report(posts, "Summary", cfg)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_xss_in_post_text_escaped(self):
        cfg = AnalysisConfig(keywords=["AI"])
        posts = [make_post(text='<img src=x onerror=alert(1)>')]
        html = build_report(posts, "Summary", cfg)
        assert "<img" not in html

    def test_stats_show_post_count(self):
        cfg = AnalysisConfig(keywords=["AI"])
        posts = [make_post(), make_post(id="2", author="User2")]
        html = build_report(posts, "Summary", cfg)
        assert ">2<" in html  # Stat-Zahl für Posts

    def test_empty_posts_list(self):
        cfg = AnalysisConfig(keywords=["AI"])
        html = build_report([], "Keine Posts gefunden.", cfg)
        assert "<!DOCTYPE html>" in html
        assert "Keine Posts gefunden." in html

    def test_post_url_is_rendered_as_link(self):
        cfg = AnalysisConfig(keywords=["AI"])
        posts = [make_post(url="https://linkedin.com/posts/test123")]
        html = build_report(posts, "Summary", cfg)
        assert "https://linkedin.com/posts/test123" in html

    def test_no_url_no_link(self):
        cfg = AnalysisConfig(keywords=["AI"])
        posts = [make_post(url="")]
        html = build_report(posts, "Summary", cfg)
        assert "→ Post auf LinkedIn öffnen" not in html
