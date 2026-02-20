"""
Tests für app/analyzer.py – Konfiguration, Datenmodelle und Normalisierung
"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from app.analyzer import AnalysisConfig, Post, LinkedInAnalyzer, AnthropicClient


# ── AnalysisConfig ────────────────────────────────────────────────────────────

class TestAnalysisConfig:
    def test_keywords_str_single(self):
        cfg = AnalysisConfig(keywords=["Agentic AI"])
        assert cfg.keywords_str == "Agentic AI"

    def test_keywords_str_multiple(self):
        cfg = AnalysisConfig(keywords=["AI", "LLM", "Claude"])
        assert cfg.keywords_str == "AI, LLM, Claude"

    def test_apify_date_filter_7(self):
        cfg = AnalysisConfig(keywords=["AI"], days=7)
        assert cfg.apify_date_filter == "past-week"

    def test_apify_date_filter_14(self):
        cfg = AnalysisConfig(keywords=["AI"], days=14)
        assert cfg.apify_date_filter == "past-2-weeks"

    def test_apify_date_filter_30(self):
        cfg = AnalysisConfig(keywords=["AI"], days=30)
        assert cfg.apify_date_filter == "past-month"

    def test_apify_date_filter_unknown_falls_back_to_week(self):
        cfg = AnalysisConfig(keywords=["AI"], days=21)
        assert cfg.apify_date_filter == "past-week"

    def test_defaults(self):
        cfg = AnalysisConfig(keywords=["AI"])
        assert cfg.days == 7
        assert cfg.max_posts_per_keyword == 25
        assert cfg.include_comments is True


# ── Post ─────────────────────────────────────────────────────────────────────

def make_post(**kwargs) -> Post:
    defaults = dict(
        id="123",
        keyword="AI",
        author="Max Mustermann",
        author_title="CEO",
        author_url="https://linkedin.com/in/max",
        text="Das ist ein Testpost über Künstliche Intelligenz.",
        posted_at="2025-05-01T10:00:00Z",
        likes=42,
        comments=5,
        reposts=3,
        url="https://linkedin.com/posts/123",
    )
    defaults.update(kwargs)
    return Post(**defaults)


class TestPost:
    def test_engagement_score(self):
        post = make_post(likes=10, comments=5, reposts=2)
        # likes + comments*2 + reposts = 10 + 10 + 2 = 22
        assert post.engagement_score == 22

    def test_engagement_score_zeros(self):
        post = make_post(likes=0, comments=0, reposts=0)
        assert post.engagement_score == 0

    def test_to_dict_contains_all_fields(self):
        post = make_post()
        d = post.to_dict()
        assert "id" in d
        assert "author" in d
        assert "sentiment_post" in d
        assert "engagement_score" not in d  # property, not field

    def test_default_sentiment_values(self):
        post = make_post()
        assert post.sentiment_post == "neutral"
        assert post.sentiment_score == 0.0
        assert post.sentiment_comments == "keine"
        assert post.main_topics == []
        assert post.summary == ""
        assert post.notable_comment == ""


# ── _normalize_post ───────────────────────────────────────────────────────────

class TestNormalizePost:
    def setup_method(self):
        cfg = AnalysisConfig(keywords=["AI"])
        self.analyzer = LinkedInAnalyzer(cfg)

    def test_basic_normalization(self):
        raw = {
            "id": "abc123",
            "text": "Ein längerer Testtext mit mehr als zwanzig Zeichen.",
            "authorName": "Maria Muster",
            "authorHeadline": "CTO",
            "authorUrl": "https://linkedin.com/in/maria",
            "postedAt": "2025-05-01",
            "likeCount": 100,
            "commentCount": 20,
            "repostCount": 5,
            "url": "https://linkedin.com/posts/abc123",
        }
        post = self.analyzer._normalize_post(raw, "AI")
        assert post is not None
        assert post.author == "Maria Muster"
        assert post.likes == 100
        assert post.comments == 20
        assert post.reposts == 5

    def test_short_text_returns_none(self):
        raw = {"text": "Zu kurz"}
        post = self.analyzer._normalize_post(raw, "AI")
        assert post is None

    def test_empty_text_returns_none(self):
        raw = {"text": ""}
        post = self.analyzer._normalize_post(raw, "AI")
        assert post is None

    def test_alternative_field_names(self):
        """Prüft Schema-Kompatibilität mit alternativem Apify-Actor."""
        raw = {
            "postId": "xyz",
            "postText": "Ein ausreichend langer Beitragstext für den Test hier.",
            "posterFullName": "Klaus Klein",
            "posterTitle": "Manager",
            "posterProfileUrl": "https://linkedin.com/in/kk",
            "publishedAt": "2025-04-15",
            "likes": 50,
            "commentsCount": 10,
            "sharesCount": 2,
            "postUrl": "https://linkedin.com/posts/xyz",
        }
        post = self.analyzer._normalize_post(raw, "LLM")
        assert post is not None
        assert post.author == "Klaus Klein"
        assert post.likes == 50
        assert post.reposts == 2
        assert post.keyword == "LLM"

    def test_nested_author_object(self):
        raw = {
            "id": "n1",
            "text": "Testbeitrag mit genug Text für die Mindestlänge hier.",
            "author": {"name": "Anna Analyse", "headline": "Data Scientist", "url": "https://li.com"},
            "postedAt": "2025-05-01",
            "likeCount": 0,
            "commentCount": 0,
            "repostCount": 0,
        }
        post = self.analyzer._normalize_post(raw, "AI")
        assert post is not None
        assert post.author == "Anna Analyse"
        assert post.author_title == "Data Scientist"

    def test_comments_list_parsed(self):
        raw = {
            "id": "c1",
            "text": "Beitrag mit Kommentaren – ausreichend lang für den Test.",
            "authorName": "Bob",
            "likeCount": 0,
            "commentCount": 2,
            "repostCount": 0,
            "topComments": [
                {"author": {"name": "Alice"}, "text": "Toller Post!"},
                {"authorName": "Charlie", "commentText": "Interessant."},
            ],
        }
        post = self.analyzer._normalize_post(raw, "AI")
        assert post is not None
        assert len(post.comments_list) == 2
        assert post.comments_list[0]["author"] == "Alice"
        assert post.comments_list[0]["text"] == "Toller Post!"

    def test_id_falls_back_to_url_or_hash(self):
        raw = {
            "text": "Ein Post ohne explizite ID, aber mit genug Text hier.",
            "url": "https://linkedin.com/posts/fallback",
            "authorName": "Fallback User",
            "likeCount": 0,
            "commentCount": 0,
            "repostCount": 0,
        }
        post = self.analyzer._normalize_post(raw, "AI")
        assert post is not None
        assert post.id == "https://linkedin.com/posts/fallback"

    def test_missing_numeric_fields_default_to_zero(self):
        raw = {
            "id": "zero",
            "text": "Post ohne Metriken – Text ist aber lang genug für den Test.",
            "authorName": "Zero",
        }
        post = self.analyzer._normalize_post(raw, "AI")
        assert post is not None
        assert post.likes == 0
        assert post.comments == 0
        assert post.reposts == 0


# ── AnthropicClient (gemockt) ─────────────────────────────────────────────────

class TestAnthropicClientSentiment:
    async def test_sentiment_returns_parsed_json(self):
        sentiment_data = {
            "sentiment_post": "positiv",
            "sentiment_score": 0.8,
            "sentiment_comments": "neutral",
            "main_topics": ["KI", "Innovation"],
            "summary": "Ein sehr positiver Beitrag über KI.",
            "notable_comment": "",
        }
        client = AnthropicClient("test-key")
        post = make_post()

        with patch.object(client, "_post", new=AsyncMock(return_value=json.dumps(sentiment_data))):
            result = await client.sentiment(post)

        await client.aclose()
        assert result["sentiment_post"] == "positiv"
        assert result["sentiment_score"] == 0.8
        assert "KI" in result["main_topics"]

    async def test_sentiment_handles_json_in_markdown_block(self):
        """Claude gibt manchmal JSON in Markdown-Backticks zurück – muss trotzdem funktionieren."""
        inner = json.dumps({
            "sentiment_post": "negativ",
            "sentiment_score": -0.5,
            "sentiment_comments": "keine",
            "main_topics": ["Kritik"],
            "summary": "Kritischer Beitrag.",
            "notable_comment": "",
        })
        client = AnthropicClient("test-key")
        post = make_post()

        with patch.object(client, "_post", new=AsyncMock(return_value=f"```json\n{inner}\n```")):
            result = await client.sentiment(post)

        await client.aclose()
        assert result["sentiment_post"] == "negativ"

    async def test_sentiment_returns_empty_dict_on_invalid_json(self):
        client = AnthropicClient("test-key")
        post = make_post()

        with patch.object(client, "_post", new=AsyncMock(return_value="Keine JSON-Antwort hier.")):
            result = await client.sentiment(post)

        await client.aclose()
        assert result == {}
