"""
LinkedIn Post Analyzer – FastAPI Backend
Supports:
  - Web UI:  uvicorn app.main:app
  - CLI:     python -m app.main --keywords "AI, LLM" --days 7
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analyzer import LinkedInAnalyzer, AnalysisConfig
from .report import build_report

# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="LinkedIn Post Analyzer", version="1.0.0")

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
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


@app.post("/analyze", response_class=HTMLResponse)
async def analyze_sync(
    keywords: str = Form(...),
    days: int = Form(7),
    max_posts: int = Form(25),
    include_comments: bool = Form(True),
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


# ── CLI-Mode ──────────────────────────────────────────────────────────────────
async def cli_main(args):
    config = AnalysisConfig(
        keywords=[k.strip() for k in args.keywords.split(",") if k.strip()],
        days=args.days,
        max_posts_per_keyword=args.max_posts,
        include_comments=not args.no_comments,
    )

    print(f"\n🔍 LinkedIn Analyzer – CLI Mode")
    print(f"   Keywords : {', '.join(config.keywords)}")
    print(f"   Zeitraum : letzte {config.days} Tage")
    print(f"   Max Posts: {config.max_posts_per_keyword} / Keyword\n")

    analyzer = LinkedInAnalyzer(config)
    async for event in analyzer.run_stream():
        if event["type"] == "progress":
            print(f"   ⏳ {event['message']}")
        elif event["type"] == "done":
            posts = event["posts"]
            summary = event["summary"]
            html = build_report(posts, summary, config)

            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html, encoding="utf-8")
            print(f"\n✅ Report gespeichert: {out_path}")
            print(f"   Posts analysiert : {len(posts)}")
        elif event["type"] == "error":
            print(f"\n❌ Fehler: {event['message']}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Post Analyzer")
    sub = parser.add_subparsers(dest="cmd")

    # CLI-Modus
    cli = sub.add_parser("analyze", help="Analyse ausführen und HTML-Datei speichern")
    cli.add_argument("--keywords", required=True, help='Kommagetrennt, z.B. "AI,LLM"')
    cli.add_argument("--days", type=int, default=7, help="Zeitraum in Tagen (default: 7)")
    cli.add_argument("--max-posts", type=int, default=25, help="Max Posts pro Keyword")
    cli.add_argument("--no-comments", action="store_true", help="Kommentare nicht laden")
    cli.add_argument("--output", default="/output/report.html", help="Ausgabepfad")

    # Web-Server-Modus
    serve = sub.add_parser("serve", help="Web-Server starten")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8080)

    args = parser.parse_args()

    if args.cmd == "analyze":
        asyncio.run(cli_main(args))
    elif args.cmd == "serve":
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
    else:
        # Default: Web-Server
        uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=False)
