"""
Tests für app/report.py – HTML-Escape, Badges, Score-Bar und Report-Generierung
"""

import pytest
from app.report import _esc, _sentiment_badge, _score_bar, _format_date, _summary_to_html, _render_inline, _parse_table, build_report
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


# ── _render_inline ────────────────────────────────────────────────────────────

class TestRenderInline:
    def test_bold_converted_to_strong(self):
        assert _render_inline("**fett**") == "<strong>fett</strong>"

    def test_bold_mid_sentence(self):
        result = _render_inline("Ein **wichtiger** Begriff")
        assert "<strong>wichtiger</strong>" in result
        assert "Ein" in result

    def test_html_special_chars_escaped(self):
        result = _render_inline("<b>kein tag</b>")
        assert "<b>" not in result
        assert "&lt;b&gt;" in result

    def test_bold_and_escape_combined(self):
        result = _render_inline("**Wert: <100%**")
        assert "<strong>" in result
        assert "&lt;100%&gt;" not in result  # % ist kein HTML-Sonderzeichen
        assert "&lt;100" in result  # < wurde escaped


# ── _parse_table ──────────────────────────────────────────────────────────────

class TestParseTable:
    def test_basic_table_produces_html_table(self):
        rows = [
            "| Sentiment | Anzahl | Anteil |",
            "|-----------|--------|--------|",
            "| positiv   | 12     | 60 %   |",
            "| negativ   | 8      | 40 %   |",
        ]
        html = _parse_table(rows)
        assert "<table" in html
        assert "<thead>" in html
        assert "<tbody>" in html
        assert "<th>" in html
        assert "<td>" in html

    def test_header_cells_in_thead(self):
        rows = ["| A | B |", "|---|---|", "| 1 | 2 |"]
        html = _parse_table(rows)
        assert "<th>A</th>" in html
        assert "<th>B</th>" in html

    def test_data_rows_in_tbody(self):
        rows = ["| Typ | Wert |", "|-----|------|", "| KI  | hoch |"]
        html = _parse_table(rows)
        assert "<td>KI</td>" in html
        assert "<td>hoch</td>" in html

    def test_separator_row_not_in_body(self):
        rows = ["| A | B |", "|---|---|", "| x | y |"]
        html = _parse_table(rows)
        assert "---" not in html

    def test_bold_in_cell_rendered(self):
        rows = ["| Score |", "|-------|", "| **0,85** |"]
        html = _parse_table(rows)
        assert "<strong>0,85</strong>" in html

    def test_xss_in_cell_escaped(self):
        rows = ["| Titel |", "|-------|", '| <script>alert(1)</script> |']
        html = _parse_table(rows)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_summary_table_css_class(self):
        rows = ["| H |", "|---|", "| v |"]
        html = _parse_table(rows)
        assert 'class="summary-table"' in html


# ── _summary_to_html (Tabellen) ───────────────────────────────────────────────

class TestSummaryToHtml:
    def test_markdown_table_becomes_html_table(self):
        md = "## Überschrift\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
        html = _summary_to_html(md)
        assert "<table" in html
        assert "<th>A</th>" in html
        assert "<td>1</td>" in html

    def test_heading_still_works(self):
        html = _summary_to_html("## Mein Titel")
        assert '<h3 class="sum-h3">' in html
        assert "Mein Titel" in html

    def test_bold_in_paragraph(self):
        html = _summary_to_html("Das ist **wichtig**.")
        assert "<strong>wichtig</strong>" in html

    def test_mixed_content(self):
        md = (
            "## Sentiments\n\n"
            "| Typ | n |\n|-----|---|\n| positiv | 5 |\n\n"
            "Fazit: **sehr positiv**."
        )
        html = _summary_to_html(md)
        assert "<table" in html
        assert "<strong>sehr positiv</strong>" in html
        assert "<h3" in html
