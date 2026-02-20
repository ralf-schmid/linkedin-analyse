"""
Kern-Logik: LinkedIn Posts via Apify scrapen + Claude Sentiment-Analyse
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import httpx


# ── Konfiguration ─────────────────────────────────────────────────────────────
@dataclass
class AnalysisConfig:
    keywords: list[str]
    days: int = 7
    max_posts_per_keyword: int = 25
    include_comments: bool = True

    @property
    def apify_date_filter(self) -> str:
        return {7: "past-week", 14: "past-2-weeks", 30: "past-month"}.get(
            self.days, "past-week"
        )

    @property
    def keywords_str(self) -> str:
        return ", ".join(self.keywords)


@dataclass
class Post:
    id: str
    keyword: str
    author: str
    author_title: str
    author_url: str
    text: str
    posted_at: str
    likes: int
    comments: int
    reposts: int
    url: str
    comments_list: list[dict] = field(default_factory=list)
    # Sentiment (wird später gefüllt)
    sentiment_post: str = "neutral"
    sentiment_score: float = 0.0
    sentiment_comments: str = "keine"
    main_topics: list[str] = field(default_factory=list)
    summary: str = ""
    notable_comment: str = ""

    @property
    def engagement_score(self) -> int:
        return self.likes + self.comments * 2 + self.reposts

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ── API-Clients ───────────────────────────────────────────────────────────────
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Apify Actor – alternatives: "jiri.spilka~linkedin-post-scraper"
APIFY_ACTOR = os.environ.get(
    "APIFY_ACTOR", "harvestapi~linkedin-post-search"
)
CLAUDE_HAIKU = "claude-haiku-4-5-20251001"
CLAUDE_SONNET = "claude-sonnet-4-6"


class ApifyClient:
    BASE = "https://api.apify.com/v2"

    def __init__(self, token: str):
        self.token = token

    async def scrape_linkedin(
        self, keyword: str, config: AnalysisConfig, timeout: int = 180
    ) -> list[dict]:
        url = f"{self.BASE}/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"
        payload = {
            "searchKeywords": keyword,
            "maxResults": config.max_posts_per_keyword,
            "datePosted": config.apify_date_filter,
            "scrapeComments": config.include_comments,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                params={"token": self.token},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else [data]


class AnthropicClient:
    BASE = "https://api.anthropic.com/v1"
    HEADERS = {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    def __init__(self, api_key: str):
        self.headers = {**self.HEADERS, "x-api-key": api_key}
        # Reuse a single client across all calls to avoid per-request TCP handshakes
        self._client = httpx.AsyncClient(timeout=90)

    async def _post(self, payload: dict, timeout: int = 60) -> str:
        resp = await self._client.post(
            f"{self.BASE}/messages",
            headers=self.headers,
            json=payload,
            extensions={"timeout": {"read": timeout, "connect": 10, "write": 10, "pool": 5}},
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    async def aclose(self) -> None:
        await self._client.aclose()

    async def sentiment(self, post: Post) -> dict:
        comments_text = json.dumps(
            [{"author": c.get("author", ""), "text": c.get("text", "")}
             for c in post.comments_list[:10]],
            ensure_ascii=False,
        )
        prompt = (
            f"Analysiere diesen LinkedIn-Post:\\n\\n"
            f"Autor: {post.author} ({post.author_title})\\n"
            f"Text: {post.text[:2000]}\\n"
            f"Kommentare: {comments_text}\\n\\n"
            "Antworte NUR mit einem JSON-Objekt (kein Markdown, keine Erklärung):\\n"
            "{\\n"
            '  "sentiment_post": "positiv|neutral|negativ|gemischt",\\n'
            '  "sentiment_score": -1.0 bis 1.0,\\n'
            '  "sentiment_comments": "positiv|neutral|negativ|gemischt|keine",\\n'
            '  "main_topics": ["Thema1", "Thema2", "Thema3"],\\n'
            '  "summary": "2-3 Sätze Zusammenfassung des Posts",\\n'
            '  "notable_comment": "Bemerkenswertester Kommentar oder leerer String"\\n'
            "}"
        )
        raw = await self._post({
            "model": CLAUDE_HAIKU,
            "max_tokens": 600,
            "system": (
                "Du bist ein Social-Media-Analyst. Analysiere LinkedIn-Posts auf Deutsch. "
                "Antworte IMMER nur mit validem JSON, ohne Markdown-Backticks."
            ),
            "messages": [{"role": "user", "content": prompt}],
        })
        # JSON robust extrahieren
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            return json.loads(match.group())
        return {}

    async def summarize(self, posts: list[Post], config: AnalysisConfig) -> str:
        overview = "\n".join(
            f"{i+1}. {p.author}: {p.summary} | "
            f"Sentiment: {p.sentiment_post} (Score: {p.sentiment_score:.2f}) | "
            f"Likes: {p.likes} | Kommentare: {p.comments} | "
            f"Keyword: '{p.keyword}'"
            for i, p in enumerate(posts)
        )
        prompt = (
            f"Du hast {len(posts)} LinkedIn-Posts zum Thema \"{config.keywords_str}\" "
            f"aus den letzten {config.days} Tagen analysiert.\\n\\n"
            f"Post-Übersicht:\\n{overview}\\n\\n"
            "Erstelle einen strukturierten Analysebericht mit diesen Abschnitten:\\n\\n"
            "## 1. EXECUTIVE SUMMARY\\n"
            "5-7 Sätze: Was wird aktuell diskutiert? Kernbotschaften?\\n\\n"
            "## 2. STIMMUNGSBILD\\n"
            "Dominante Sentiments, Trends, Tonalität\\n\\n"
            "## 3. TOP-THEMEN\\n"
            "Die 5 wichtigsten diskutierten Aspekte\\n\\n"
            "## 4. MEINUNGSFÜHRER\\n"
            "Autoren mit besonders hohem Engagement\\n\\n"
            "## 5. AUFFÄLLIGKEITEN\\n"
            "Kontroversen, Ausreißer, besondere Trends"
        )
        return await self._post(
            {
                "model": CLAUDE_SONNET,
                "max_tokens": 2500,
                "system": (
                    "Du bist ein Senior-Analyst für Social-Media und LinkedIn. "
                    "Erstelle professionelle, präzise Berichte auf Deutsch."
                ),
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=90,
        )


# ── Hauptanalyse-Klasse ───────────────────────────────────────────────────────
class LinkedInAnalyzer:
    def __init__(self, config: AnalysisConfig):
        self.config = config
        self._apify = ApifyClient(APIFY_TOKEN)
        self._claude = AnthropicClient(ANTHROPIC_KEY)

    def _normalize_post(self, raw: dict, keyword: str) -> Optional[Post]:
        """Verschiedene Apify-Actor-Schemas normalisieren."""
        text = raw.get("text") or raw.get("content") or raw.get("postText") or ""
        if len(text.strip()) < 20:
            return None

        uid = (
            raw.get("id")
            or raw.get("postId")
            or raw.get("urn")
            or raw.get("url")
            or raw.get("postUrl")
            or str(hash(text[:100]))
        )

        author_obj = raw.get("author") or {}
        author = (
            author_obj.get("name")
            or raw.get("authorName")
            or raw.get("posterFullName")
            or "Unbekannt"
        )
        author_title = (
            author_obj.get("headline")
            or raw.get("authorHeadline")
            or raw.get("posterTitle")
            or ""
        )
        author_url = (
            author_obj.get("url")
            or raw.get("authorUrl")
            or raw.get("posterProfileUrl")
            or ""
        )

        raw_comments = (
            raw.get("topComments")
            or raw.get("commentsList")
            or raw.get("comments_list")
            or []
        )
        comments_list = [
            {
                "author": (
                    c.get("author", {}).get("name")
                    or c.get("authorName")
                    or c.get("commenterName")
                    or "Anonym"
                ),
                "text": c.get("text") or c.get("content") or c.get("commentText") or "",
            }
            for c in (raw_comments if isinstance(raw_comments, list) else [])
            if isinstance(c, dict)
        ]

        return Post(
            id=str(uid),
            keyword=keyword,
            author=author,
            author_title=author_title,
            author_url=author_url,
            text=text,
            posted_at=raw.get("postedAt") or raw.get("publishedAt") or raw.get("date") or "",
            likes=int(raw.get("likeCount") or raw.get("likes") or raw.get("reactionsCount") or 0),
            comments=int(raw.get("commentCount") or raw.get("commentsCount") or 0),
            reposts=int(raw.get("repostCount") or raw.get("repostsCount") or raw.get("sharesCount") or 0),
            url=raw.get("url") or raw.get("postUrl") or raw.get("linkedinUrl") or "",
            comments_list=comments_list,
        )

    async def run_stream(self) -> AsyncIterator[dict]:
        """Async-Generator: liefert Fortschritts-Events als Dicts."""
        config = self.config
        all_posts: list[Post] = []
        seen_ids: set[str] = set()

        # ── Phase 1: Scraping ──────────────────────────────────────────────
        for i, keyword in enumerate(config.keywords):
            yield {
                "type": "progress",
                "phase": "scraping",
                "message": f"Scrape LinkedIn fuer Keyword '{keyword}' ({i+1}/{len(config.keywords)}) ...",
                "percent": int(10 + (i / len(config.keywords)) * 30),
            }
            try:
                raw_posts = await self._apify.scrape_linkedin(keyword, config)
            except httpx.HTTPStatusError as exc:
                yield {
                    "type": "warning",
                    "message": f"Apify-Fehler fuer Keyword '{keyword}': {exc.response.status_code} - {exc.response.text[:200]}",
                }
                continue
            except Exception as exc:
                yield {"type": "warning", "message": f"Scraping-Fehler fuer Keyword '{keyword}': {exc}"}
                continue

            for raw in raw_posts:
                post = self._normalize_post(raw, keyword)
                if post and post.id not in seen_ids:
                    seen_ids.add(post.id)
                    all_posts.append(post)

        yield {
            "type": "progress",
            "phase": "dedup",
            "message": f"{len(all_posts)} Posts gesammelt (dedupliziert). Sortiere nach Engagement ...",
            "percent": 45,
        }

        # Nach Engagement sortieren
        all_posts.sort(key=lambda p: p.engagement_score, reverse=True)

        if not all_posts:
            yield {
                "type": "error",
                "message": "Keine Posts gefunden. Bitte Keywords oder Zeitraum anpassen.",
            }
            return

        # ── Phase 2: Sentiment je Post ─────────────────────────────────────
        for i, post in enumerate(all_posts):
            yield {
                "type": "progress",
                "phase": "sentiment",
                "message": f"Sentiment-Analyse Post {i+1}/{len(all_posts)}: {post.author} ...",
                "percent": int(45 + (i / len(all_posts)) * 40),
            }
            try:
                result = await self._claude.sentiment(post)
                post.sentiment_post = result.get("sentiment_post", "neutral")
                post.sentiment_score = float(result.get("sentiment_score", 0.0))
                post.sentiment_comments = result.get("sentiment_comments", "keine")
                post.main_topics = result.get("main_topics", [])
                post.summary = result.get("summary", "")
                post.notable_comment = result.get("notable_comment", "")
            except Exception as exc:
                yield {"type": "warning", "message": f"Sentiment-Fehler Post {i+1}: {exc}"}

        # ── Phase 3: Gesamt-Zusammenfassung ───────────────────────────────
        yield {
            "type": "progress",
            "phase": "summary",
            "message": "Erstelle Executive Summary ...",
            "percent": 88,
        }
        try:
            summary = await self._claude.summarize(all_posts, config)
        except Exception as exc:
            summary = f"Zusammenfassung konnte nicht erstellt werden: {exc}"

        await self._claude.aclose()

        yield {
            "type": "done",
            "message": "Analyse abgeschlossen.",
            "percent": 100,
            "posts": [p.to_dict() for p in all_posts],
            "summary": summary,
        }

    async def run(self) -> tuple[list[Post], str]:
        """Synchroner Wrapper für den CLI-Modus."""
        posts = []
        summary = ""
        async for event in self.run_stream():
            if event["type"] == "done":
                summary = event["summary"]
                # Posts aus Dicts rekonstruieren
                for d in event["posts"]:
                    p = Post(**{k: v for k, v in d.items() if k in Post.__dataclass_fields__})
                    posts.append(p)
            elif event["type"] == "error":
                raise RuntimeError(event["message"])
        return posts, summary
