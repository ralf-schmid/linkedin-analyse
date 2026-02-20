"""
LinkedIn Post Analyzer – FastAPI Backend
Supports:
  - Web UI:  uvicorn app.main:app
  - CLI:     python -m app.main --keywords "AI, LLM" --days 7
"""

import argparse
import asyncio
import json
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analyzer import LinkedInAnalyzer, AnalysisConfig
from .report import build_report

# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="LinkedIn Post Analyzer", version="1.0.0")

# ── HTTP Basic Auth ───────────────────────────────────────────────────────────
_WEB_USER = os.environ.get("WEB_USER", "")
_WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "")

_http_basic = HTTPBasic(auto_error=False)


def require_auth(credentials: HTTPBasicCredentials = Depends(_http_basic)):
    """Dependency: erzwingt HTTP Basic Auth wenn WEB_USER + WEB_PASSWORD gesetzt sind.
    Ist keine der Variablen gesetzt, wird der Zugriff ohne Authentifizierung erlaubt."""
    if not _WEB_USER or not _WEB_PASSWORD:
        return  # Auth deaktiviert

    valid = credentials is not None and (
        secrets.compare_digest(credentials.username.encode(), _WEB_USER.encode())
        and secrets.compare_digest(credentials.password.encode(), _WEB_PASSWORD.encode())
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Zugangsdaten",
            headers={"WWW-Authenticate": 'Basic realm="LinkedIn Analyzer"'},
        )

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, _: None = Depends(require_auth)):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.post("/analyze/stream")
async def analyze_stream(
    keywords: str = Form(...),
    days: int = Form(7),
    max_posts: int = Form(25),
    include_comments: bool = Form(True),
    _: None = Depends(require_auth),
):
    """
    Server-Sent Events stream – schickt Fortschritts-Events während der Analyse
    und am Ende das fertige HTML-Report als letztes Event.
    """
    config = AnalysisConfig(
        keywords=[k.strip() for k in keywords.split(",") if k.strip()],
        days=days,
        max_posts_per_keyword=max_posts,
        include_comments=include_comments,
    )

    async def event_stream():
        try:
            analyzer = LinkedInAnalyzer(config)
            async for event in analyzer.run_stream():
                if event["type"] == "done":
                    # Build and embed the HTML report so the client doesn't need a second request
                    from .analyzer import Post
                    posts = [
                        Post(**{k: v for k, v in d.items() if k in Post.__dataclass_fields__})
                        for d in event["posts"]
                    ]
                    event["html"] = build_report(posts, event["summary"], config)
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # wichtig für nginx reverse proxy
        },
    )


@app.post("/report", response_class=HTMLResponse)
async def report_endpoint(
    request: Request,
    _: None = Depends(require_auth),
):
    """Generiert HTML-Report aus manuell gefilterten Posts.

    Erstellt die Executive Summary neu auf Basis der gefilterten Posts,
    damit ausgeschlossene Posts komplett ignoriert werden.
    """
    body = await request.json()
    from .analyzer import Post, AnthropicClient, ANTHROPIC_KEY
    posts = [
        Post(**{k: v for k, v in d.items() if k in Post.__dataclass_fields__})
        for d in body.get("posts", [])
    ]
    config = AnalysisConfig(
        keywords=[k.strip() for k in body.get("keywords", "").split(",") if k.strip()],
        days=int(body.get("days", 7)),
    )

    # Summary immer neu auf gefilterter Grundgesamtheit berechnen
    summary = body.get("summary", "")
    if ANTHROPIC_KEY and posts:
        client = AnthropicClient(ANTHROPIC_KEY)
        try:
            summary = await client.summarize(posts, config)
        except Exception:
            pass  # Original-Summary als Fallback
        finally:
            await client.aclose()

    return HTMLResponse(content=build_report(posts, summary, config))


@app.post("/analyze", response_class=HTMLResponse)
async def analyze_sync(
    keywords: str = Form(...),
    days: int = Form(7),
    max_posts: int = Form(25),
    include_comments: bool = Form(True),
    _: None = Depends(require_auth),
):
    """Synchroner Fallback – gibt fertigen HTML-Report zurück."""
    config = AnalysisConfig(
        keywords=[k.strip() for k in keywords.split(",") if k.strip()],
        days=days,
        max_posts_per_keyword=max_posts,
        include_comments=include_comments,
    )
    analyzer = LinkedInAnalyzer(config)
    posts, summary = await analyzer.run()
    return HTMLResponse(content=build_report(posts, summary, config))


# ── CLI-Helpers ───────────────────────────────────────────────────────────────
def _print_event(event: dict) -> None:
    """Gibt ein SSE-Event lesbar auf der Konsole aus."""
    pct = event.get("percent", 0)
    msg = event["message"]
    phase = event.get("phase", "")
    if event["type"] == "progress":
        if phase == "cache":
            print(f"   💾 [{pct:3d}%] {msg}")
        elif phase in ("sentiment_result",):
            print(f"         {msg}")
        else:
            print(f"   ⏳ [{pct:3d}%] {msg}")
    elif event["type"] == "warning":
        print(f"   ⚠️  {msg}")
    elif event["type"] == "error":
        print(f"\n❌ {msg}", file=sys.stderr)


def _print_post_list(posts: list) -> None:
    """Gibt alle analysierten Posts nummeriert in der Konsole aus."""
    sep = "─" * 74
    print(f"\n📋 {len(posts)} Posts gefunden:\n{sep}")
    for i, p in enumerate(posts):
        score_str = f"{p.sentiment_score:+.2f}"
        text_preview = (p.text or "").replace("\n", " ")[:90]
        ellipsis = "…" if len(p.text or "") > 90 else ""
        title_part = f" · {p.author_title[:55]}" if p.author_title else ""
        print(
            f"\n  [{i+1:2d}]  {p.author}{title_part}\n"
            f"        via \"{p.keyword}\"  |  "
            f"👍 {p.likes}  💬 {p.comments}  🔁 {p.reposts}  |  "
            f"{p.sentiment_post} ({score_str})\n"
            f"        \"{text_preview}{ellipsis}\""
        )
    print(f"\n{sep}")


def _prompt_exclusion(posts: list) -> list:
    """Interaktive Post-Filterung.

    Nutzer gibt kommagetrennte 1-basierte Nummern der auszuschließenden Posts ein.
    Eingabe leer → alle Posts behalten. EOFError/KeyboardInterrupt → alle behalten.
    """
    print(
        "Nicht relevante Posts ausschließen\n"
        "(Nummern kommagetrennt, z.B. 2,5,8 – oder Enter zum Überspringen): ",
        end="",
        flush=True,
    )
    try:
        raw = input().strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return posts

    if not raw:
        return posts

    exclude: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1  # 1-basiert → 0-basiert
            if 0 <= idx < len(posts):
                exclude.add(idx)
            else:
                print(f"   ⚠️  Nummer {int(part)} außerhalb des gültigen Bereichs – ignoriert.")
        elif part:
            print(f"   ⚠️  \"{part}\" ist keine gültige Zahl – ignoriert.")

    filtered = [p for i, p in enumerate(posts) if i not in exclude]
    if exclude:
        print(f"\n   ✂️  {len(exclude)} Post(s) ausgeschlossen → {len(filtered)} verbleiben.")
    return filtered


def _save_report(posts: list, summary: str, config: AnalysisConfig, output_path: str) -> None:
    html = build_report(posts, summary, config)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"\n✅ Report gespeichert : {out}")
    print(f"   Posts im Report   : {len(posts)}")


# ── CLI-Mode ──────────────────────────────────────────────────────────────────
async def cli_main(args):
    config = AnalysisConfig(
        keywords=[k.strip() for k in args.keywords.split(",") if k.strip()],
        days=args.days,
        max_posts_per_keyword=args.max_posts,
        include_comments=not args.no_comments,
        cache_dir=getattr(args, "save_cache", None),
    )

    print(f"\n🔍 LinkedIn Analyzer – CLI Mode")
    print(f"   Keywords : {', '.join(config.keywords)}")
    print(f"   Zeitraum : letzte {config.days} Tage")
    print(f"   Max Posts: {config.max_posts_per_keyword} / Keyword")
    if config.cache_dir:
        print(f"   Cache-Dir: {config.cache_dir}")
    print()

    analyzer = LinkedInAnalyzer(config)
    async for event in analyzer.run_stream():
        if event["type"] in ("progress", "warning"):
            _print_event(event)
        elif event["type"] == "done":
            from .analyzer import Post, AnthropicClient, ANTHROPIC_KEY
            posts = [
                Post(**{k: v for k, v in d.items() if k in Post.__dataclass_fields__})
                for d in event["posts"]
            ]
            summary = event["summary"]
            original_count = len(posts)

            # Interaktive Post-Überprüfung (nur wenn stdin ein Terminal ist)
            if not args.no_review and sys.stdin.isatty():
                _print_post_list(posts)
                posts = _prompt_exclusion(posts)

            # Summary auf gefilterter Menge neu generieren
            if len(posts) < original_count:
                print(f"\n   🤖 Erstelle neue Zusammenfassung für {len(posts)} gefilterte Posts ...")
                _claude = AnthropicClient(ANTHROPIC_KEY)
                try:
                    summary = await _claude.summarize(posts, config)
                except Exception as exc:
                    print(f"   ⚠️  Zusammenfassung fehlgeschlagen, nutze Original: {exc}")
                finally:
                    await _claude.aclose()

            _save_report(posts, summary, config, args.output)
        elif event["type"] == "error":
            _print_event(event)
            sys.exit(1)


# ── Debug-Mode ────────────────────────────────────────────────────────────────
async def debug_main(args):
    """Debug-Modus: lädt Zwischen-Cache statt echte API-Aufrufe zu starten."""
    cache_file = args.from_analysis or args.from_scrape
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
    except Exception as exc:
        print(f"\n❌ Cache-Datei konnte nicht geladen werden: {exc}", file=sys.stderr)
        sys.exit(1)

    meta = cache_data.get("meta", {})
    keywords = meta.get("keywords") or ["(unbekannt)"]

    print(f"\n🐛 LinkedIn Analyzer – Debug-Modus")
    print(f"   Cache     : {cache_file}")
    print(f"   Typ       : {'Analysis-Cache' if args.from_analysis else 'Scrape-Cache'}")
    print(f"   Keywords  : {', '.join(keywords)}")
    print(f"   Erstellt  : {meta.get('created_at', '?')}")
    print(f"   Posts     : {len(cache_data.get('posts', []))}")
    print()

    config = AnalysisConfig(
        keywords=keywords,
        days=meta.get("days", 7),
        from_scrape=args.from_scrape,
        from_analysis=args.from_analysis,
    )

    analyzer = LinkedInAnalyzer(config)
    async for event in analyzer.run_stream():
        if event["type"] in ("progress", "warning"):
            _print_event(event)
        elif event["type"] == "done":
            from .analyzer import Post, AnthropicClient, ANTHROPIC_KEY
            posts = [
                Post(**{k: v for k, v in d.items() if k in Post.__dataclass_fields__})
                for d in event["posts"]
            ]
            summary = event["summary"]
            original_count = len(posts)

            # Interaktive Post-Überprüfung (nur wenn stdin ein Terminal ist)
            if not args.no_review and sys.stdin.isatty():
                _print_post_list(posts)
                posts = _prompt_exclusion(posts)

            # Summary auf gefilterter Menge neu generieren
            if len(posts) < original_count:
                print(f"\n   🤖 Erstelle neue Zusammenfassung für {len(posts)} gefilterte Posts ...")
                _claude = AnthropicClient(ANTHROPIC_KEY)
                try:
                    summary = await _claude.summarize(posts, config)
                except Exception as exc:
                    print(f"   ⚠️  Zusammenfassung fehlgeschlagen, nutze Original: {exc}")
                finally:
                    await _claude.aclose()

            _save_report(posts, summary, config, args.output)
        elif event["type"] == "error":
            _print_event(event)
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Post Analyzer")
    sub = parser.add_subparsers(dest="cmd")

    # ── analyze: vollständige Analyse mit optionalem Cache-Speichern ──────────
    cli = sub.add_parser("analyze", help="Analyse ausführen und HTML-Datei speichern")
    cli.add_argument("--keywords", required=True, help='Kommagetrennt, z.B. "AI,LLM"')
    cli.add_argument("--days", type=int, default=7, help="Zeitraum in Tagen (default: 7)")
    cli.add_argument("--max-posts", type=int, default=25, help="Max Posts pro Keyword")
    cli.add_argument("--no-comments", action="store_true", help="Kommentare nicht laden")
    cli.add_argument("--output", default="/output/report.html", help="Ausgabepfad des HTML-Reports")
    cli.add_argument("--save-cache", metavar="DIR",
                     help="Zwischenergebnisse in diesem Verzeichnis speichern (scrape_*.json + analysis_*.json)")
    cli.add_argument("--no-review", action="store_true",
                     help="Post-Überprüfungsschritt überspringen (alle Posts in Report aufnehmen)")

    # ── debug: Analyse aus Cache wiederholen (ohne API-Kosten) ────────────────
    dbg = sub.add_parser("debug", help="Report aus gespeichertem Cache erstellen (keine API-Kosten)")
    dbg_src = dbg.add_mutually_exclusive_group(required=True)
    dbg_src.add_argument("--from-scrape", metavar="FILE",
                         help="Scrape-Cache laden → Claude Sentiment + Summary werden neu berechnet")
    dbg_src.add_argument("--from-analysis", metavar="FILE",
                         help="Analysis-Cache laden → nur Report-Generierung, keine API-Aufrufe")
    dbg.add_argument("--output", default="/output/report.html", help="Ausgabepfad des HTML-Reports")
    dbg.add_argument("--no-review", action="store_true",
                     help="Post-Überprüfungsschritt überspringen (alle Posts in Report aufnehmen)")

    # ── serve: Web-Server ─────────────────────────────────────────────────────
    serve = sub.add_parser("serve", help="Web-Server starten")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8080)

    args = parser.parse_args()

    if args.cmd == "analyze":
        asyncio.run(cli_main(args))
    elif args.cmd == "debug":
        asyncio.run(debug_main(args))
    elif args.cmd == "serve":
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
    else:
        # Default: Web-Server
        uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=False)
