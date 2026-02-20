"""
Kern-Logik: LinkedIn Posts via Apify scrapen + Claude Sentiment-Analyse
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx


# ── Konfiguration ─────────────────────────────────────────────────────────────
@dataclass
class AnalysisConfig:
    keywords: list[str]
    days: int = 7
    max_posts_per_keyword: int = 25
    include_comments: bool = True
    # Cache-Optionen
    cache_dir: Optional[str] = None       # Verzeichnis für Zwischenspeicherung
    from_scrape: Optional[str] = None     # Scrape-Cache laden (überspringt Apify)
    from_analysis: Optional[str] = None  # Analysis-Cache laden (überspringt Apify + Claude)

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

# Apify Actor – Standard: harvestapi~linkedin-post-search
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
        # harvestapi~linkedin-post-search schema:
        #   searchQueries (array), maxPosts, scrapeComments, scrapeReactions, maxReactions
        payload = {
            "searchQueries": [keyword],
            "maxPosts": config.max_posts_per_keyword,
            "scrapeComments": config.include_comments,
            "scrapeReactions": False,
            "maxReactions": 5,
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

    def _make_cache_path(self, prefix: str) -> Path:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        kw_slug = "_".join(k[:15].replace(" ", "-") for k in self.config.keywords[:2])
        return Path(self.config.cache_dir) / f"{prefix}_{ts}_{kw_slug}.json"

    def _normalize_post(self, raw: dict, keyword: str) -> Optional[Post]:
        """Verschiedene Apify-Actor-Schemas normalisieren.

        Unterstützt:
          - harvestapi~linkedin-post-search  (commentary, actor, numComments, numShares, ...)
          - curious_coder~linkedin-post-search-scraper  (text, author, likeCount, ...)
          - jiri.spilka~linkedin-post-scraper  (postText, posterFullName, ...)
        """
        # ── Text ──────────────────────────────────────────────────────────────
        # harvestapi: "commentary" | andere: "text", "content", "postText"
        text = raw.get("commentary") or raw.get("text") or raw.get("content") or raw.get("postText") or ""
        if len(text.strip()) < 20:
            return None

        # ── ID ────────────────────────────────────────────────────────────────
        uid = (
            raw.get("id")
            or raw.get("postId")
            or raw.get("urn")
            or raw.get("linkedinUrl")
            or raw.get("url")
            or raw.get("postUrl")
            or str(hash(text[:100]))
        )

        # ── Autor ─────────────────────────────────────────────────────────────
        # harvestapi: "actor" | andere: "author"
        author_obj = raw.get("actor") or raw.get("author") or {}
        author = (
            author_obj.get("name")
            or raw.get("authorName")
            or raw.get("posterFullName")
            or "Unbekannt"
        )
        author_title = (
            author_obj.get("position")      # harvestapi
            or author_obj.get("headline")
            or raw.get("authorHeadline")
            or raw.get("posterTitle")
            or ""
        )
        author_url = (
            author_obj.get("linkedinUrl")   # harvestapi
            or author_obj.get("url")
            or raw.get("authorUrl")
            or raw.get("posterProfileUrl")
            or ""
        )

        # ── Datum ─────────────────────────────────────────────────────────────
        # harvestapi: "postedAt" ist ein Objekt {"date": "...", "timestamp": ...}
        posted_at_raw = raw.get("postedAt") or raw.get("publishedAt") or raw.get("date") or ""
        if isinstance(posted_at_raw, dict):
            posted_at = posted_at_raw.get("date") or str(posted_at_raw.get("timestamp", "")) or ""
        else:
            posted_at = posted_at_raw

        # ── Likes / Reaktionen ────────────────────────────────────────────────
        # harvestapi: "reactionTypeCounts" ist eine Liste von {"type": "...", "count": N}
        reaction_counts = raw.get("reactionTypeCounts") or []
        reactions_total = sum(r.get("count", 0) for r in reaction_counts if isinstance(r, dict))
        likes = int(
            raw.get("likeCount")
            or raw.get("likes")
            or raw.get("reactionsCount")
            or raw.get("totalReactionCount")
            or reactions_total
            or 0
        )

        # ── Kommentare & Reposts ───────────────────────────────────────────────
        # harvestapi: "numComments", "numShares"
        comments = int(
            raw.get("numComments")          # harvestapi
            or raw.get("commentCount")
            or raw.get("commentsCount")
            or 0
        )
        reposts = int(
            raw.get("numShares")            # harvestapi
            or raw.get("repostCount")
            or raw.get("repostsCount")
            or raw.get("sharesCount")
            or 0
        )

        # ── URL ───────────────────────────────────────────────────────────────
        url = (
            raw.get("linkedinUrl")
            or raw.get("url")
            or raw.get("postUrl")
            or ""
        )

        # ── Kommentar-Liste ───────────────────────────────────────────────────
        # harvestapi: "comments" mit actor.name + commentary
        raw_comments = (
            raw.get("comments")             # harvestapi
            or raw.get("topComments")
            or raw.get("commentsList")
            or raw.get("comments_list")
            or []
        )
        comments_list = [
            {
                "author": (
                    c.get("actor", {}).get("name")  # harvestapi
                    or c.get("author", {}).get("name")
                    or c.get("authorName")
                    or c.get("commenterName")
                    or "Anonym"
                ),
                "text": (
                    c.get("commentary")             # harvestapi
                    or c.get("text")
                    or c.get("content")
                    or c.get("commentText")
                    or ""
                ),
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
            posted_at=posted_at,
            likes=likes,
            comments=comments,
            reposts=reposts,
            url=url,
            comments_list=comments_list,
        )

    async def run_stream(self) -> AsyncIterator[dict]:
        """Async-Generator: liefert Fortschritts-Events als Dicts."""
        config = self.config

        # ── Shortcut: vollständigen Analysis-Cache laden ───────────────────────
        if config.from_analysis:
            yield {
                "type": "progress", "phase": "cache", "percent": 5,
                "message": f"Lade Analysis-Cache: {config.from_analysis} ...",
            }
            try:
                with open(config.from_analysis, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                all_posts = [
                    Post(**{k: v for k, v in d.items() if k in Post.__dataclass_fields__})
                    for d in cached["posts"]
                ]
                summary = cached["summary"]
            except Exception as exc:
                yield {"type": "error", "message": f"Fehler beim Laden des Analysis-Cache: {exc}"}
                return
            yield {
                "type": "progress", "phase": "cache", "percent": 95,
                "message": f"{len(all_posts)} Posts + Executive Summary geladen. Erstelle Report ...",
            }
            yield {
                "type": "done", "message": "Report aus Cache erstellt.", "percent": 100,
                "posts": [p.to_dict() for p in all_posts], "summary": summary,
            }
            return

        all_posts: list[Post] = []
        seen_ids: set[str] = set()

        # ── Phase 1a: Scrape-Cache laden (überspringt Apify) ──────────────────
        if config.from_scrape:
            yield {
                "type": "progress", "phase": "cache", "percent": 5,
                "message": f"Lade Scrape-Cache: {config.from_scrape} ...",
            }
            try:
                with open(config.from_scrape, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                for d in cached["posts"]:
                    p = Post(**{k: v for k, v in d.items() if k in Post.__dataclass_fields__})
                    if p.id not in seen_ids:
                        seen_ids.add(p.id)
                        all_posts.append(p)
            except Exception as exc:
                yield {"type": "error", "message": f"Fehler beim Laden des Scrape-Cache: {exc}"}
                return
            yield {
                "type": "progress", "phase": "cache", "percent": 40,
                "message": f"{len(all_posts)} Posts aus Cache geladen (Apify übersprungen).",
            }

        # ── Phase 1b: Scraping via Apify ──────────────────────────────────────
        else:
            for i, keyword in enumerate(config.keywords):
                yield {
                    "type": "progress", "phase": "scraping",
                    "message": f"Scrape LinkedIn [{i+1}/{len(config.keywords)}]: \"{keyword}\" ...",
                    "percent": int(10 + (i / len(config.keywords)) * 30),
                }
                try:
                    raw_posts = await self._apify.scrape_linkedin(keyword, config)
                except httpx.HTTPStatusError as exc:
                    yield {"type": "warning", "message": f"Apify-Fehler für \"{keyword}\": {exc.response.status_code} – {exc.response.text[:200]}"}
                    continue
                except Exception as exc:
                    yield {"type": "warning", "message": f"Scraping-Fehler für \"{keyword}\": {exc}"}
                    continue

                new_count = 0
                for raw in raw_posts:
                    post = self._normalize_post(raw, keyword)
                    if post and post.id not in seen_ids:
                        seen_ids.add(post.id)
                        all_posts.append(post)
                        new_count += 1
                yield {
                    "type": "progress", "phase": "scraping",
                    "message": f"  → \"{keyword}\": {len(raw_posts)} Posts abgerufen, {new_count} neu (gesamt unique: {len(all_posts)})",
                    "percent": int(10 + ((i + 1) / len(config.keywords)) * 30),
                }

            # Scrape-Ergebnis als Cache speichern
            if config.cache_dir and all_posts:
                cache_path = self._make_cache_path("scrape")
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "meta": {"keywords": config.keywords, "days": config.days,
                                 "created_at": datetime.now(timezone.utc).isoformat()},
                        "posts": [p.to_dict() for p in all_posts],
                    }, f, ensure_ascii=False, indent=2)
                yield {
                    "type": "progress", "phase": "cache", "percent": 42,
                    "message": f"Scrape-Cache gespeichert → {cache_path}",
                }

        yield {
            "type": "progress", "phase": "dedup", "percent": 45,
            "message": f"{len(all_posts)} Posts gesammelt (unique). Sortiere nach Engagement ...",
        }
        all_posts.sort(key=lambda p: p.engagement_score, reverse=True)

        if not all_posts:
            yield {"type": "error", "message": "Keine Posts gefunden. Bitte Keywords oder Zeitraum anpassen."}
            return

        # ── Phase 2: Sentiment je Post ────────────────────────────────────────
        for i, post in enumerate(all_posts):
            text_preview = post.text[:65].replace("\n", " ")
            yield {
                "type": "progress", "phase": "sentiment",
                "message": f"Sentiment [{i+1}/{len(all_posts)}] {post.author}: \"{text_preview}…\"",
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
                topics_str = ", ".join(post.main_topics[:3]) or "–"
                yield {
                    "type": "progress", "phase": "sentiment_result",
                    "message": f"  → {post.sentiment_post} (Score: {post.sentiment_score:+.2f}) | Themen: {topics_str}",
                    "percent": int(45 + ((i + 1) / len(all_posts)) * 40),
                }
            except Exception as exc:
                yield {"type": "warning", "message": f"Sentiment-Fehler Post {i+1}: {exc}"}

        # ── Phase 3: Executive Summary ────────────────────────────────────────
        yield {
            "type": "progress", "phase": "summary", "percent": 88,
            "message": f"Erstelle Executive Summary für {len(all_posts)} Posts (Claude Sonnet) ...",
        }
        try:
            summary = await self._claude.summarize(all_posts, config)
        except Exception as exc:
            summary = f"Zusammenfassung konnte nicht erstellt werden: {exc}"

        # Analysis-Cache speichern (Posts mit Sentiment + Summary)
        if config.cache_dir:
            cache_path = self._make_cache_path("analysis")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({
                    "meta": {"keywords": config.keywords, "days": config.days,
                             "created_at": datetime.now(timezone.utc).isoformat()},
                    "posts": [p.to_dict() for p in all_posts],
                    "summary": summary,
                }, f, ensure_ascii=False, indent=2)
            yield {
                "type": "progress", "phase": "cache", "percent": 99,
                "message": f"Analysis-Cache gespeichert → {cache_path}",
            }

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
