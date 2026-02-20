"""
HTML-Report-Generator – erzeugt den fertigen Analysebericht
"""

import re
from datetime import datetime
from .analyzer import AnalysisConfig


def _esc(s: str) -> str:
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _render_inline(text: str) -> str:
    """Escaped den Text und rendert Inline-Markdown: **fett** → <strong>."""
    text = _esc(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    return text


def _parse_table(rows: list[str]) -> str:
    """Wandelt gesammelte Markdown-Tabellenzeilen in eine HTML-Tabelle um."""

    def split_cells(row: str) -> list[str]:
        return [c.strip() for c in row.strip("|").split("|")]

    def is_separator(row: str) -> bool:
        return bool(re.fullmatch(r'[\|:\- ]+', row.strip()))

    if not rows:
        return ""

    header_cells = split_cells(rows[0])
    thead = "<tr>" + "".join(f"<th>{_render_inline(c)}</th>" for c in header_cells) + "</tr>"

    tbody = ""
    for row in rows[1:]:
        if is_separator(row):
            continue
        cells = split_cells(row)
        tbody += "<tr>" + "".join(f"<td>{_render_inline(c)}</td>" for c in cells) + "</tr>"

    return (
        '<table class="summary-table">'
        f"<thead>{thead}</thead>"
        f"<tbody>{tbody}</tbody>"
        "</table>"
    )


def _sentiment_badge(s: str) -> str:
    cfg = {
        "positiv":  ("#16a34a", "😊"),
        "negativ":  ("#dc2626", "😟"),
        "neutral":  ("#6b7280", "😐"),
        "gemischt": ("#d97706", "🤔"),
        "keine":    ("#94a3b8", "—"),
    }
    bg, icon = cfg.get(s, ("#6b7280", "?"))
    return f'<span class="badge" style="background:{bg}">{icon} {_esc(s)}</span>'


def _score_bar(score: float) -> str:
    pct = int((score + 1) * 50)
    color = "#16a34a" if score > 0.2 else "#dc2626" if score < -0.2 else "#6b7280"
    return (
        f'<div class="score-bar-wrap">'
        f'<div class="score-bar" style="width:{pct}%;background:{color}"></div>'
        f'</div><span class="score-val">{score:.2f}</span>'
    )


def _format_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return iso or "–"


def _summary_to_html(text: str) -> str:
    """Wandelt Markdown-Summary in HTML um.

    Unterstützt: ## / ### Überschriften, | Tabellen |, **fett**, Absätze.
    """
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line:
            out.append("<br>")
            i += 1
            continue

        if line.startswith("## "):
            out.append(f'<h3 class="sum-h3">{_render_inline(line[3:])}</h3>')
            i += 1
            continue

        if line.startswith("### "):
            out.append(f'<h4 class="sum-h4">{_render_inline(line[4:])}</h4>')
            i += 1
            continue

        # Tabelle: aufeinanderfolgende Zeilen, die mit | beginnen
        if line.startswith("|"):
            table_rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_rows.append(lines[i].strip())
                i += 1
            out.append(_parse_table(table_rows))
            continue

        out.append(f"<p>{_render_inline(line)}</p>")
        i += 1

    return "\n".join(out)


CSS = """
:root {
  --li-blue: #0a66c2;
  --li-blue-dark: #004182;
  --bg: #f0f4f8;
  --card: #ffffff;
  --text: #1e293b;
  --muted: #64748b;
  --border: #e2e8f0;
  --radius: 14px;
  --shadow: 0 2px 8px rgba(0,0,0,.08);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:15px}
a{color:var(--li-blue);text-decoration:none}
a:hover{text-decoration:underline}

.page{max-width:980px;margin:0 auto;padding:28px 20px 60px}

/* Header */
.header{background:linear-gradient(135deg,var(--li-blue) 0%,var(--li-blue-dark) 100%);
  color:#fff;padding:36px 32px;border-radius:var(--radius);margin-bottom:24px;position:relative;overflow:hidden}
.header::before{content:'';position:absolute;right:-60px;top:-60px;width:240px;height:240px;
  border-radius:50%;background:rgba(255,255,255,.06)}
.header h1{font-size:24px;font-weight:700;letter-spacing:-.3px;margin-bottom:10px}
.header .meta{font-size:13px;opacity:.8;display:flex;flex-wrap:wrap;gap:16px}
.header .meta span{display:flex;align-items:center;gap:5px}

/* Stats */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:14px;margin-bottom:24px}
.stat{background:var(--card);border-radius:var(--radius);padding:18px 14px;text-align:center;
  box-shadow:var(--shadow);border:1px solid var(--border)}
.stat .num{font-size:30px;font-weight:700;color:var(--li-blue);line-height:1}
.stat .lbl{font-size:12px;color:var(--muted);margin-top:5px}

/* Section */
.section{background:var(--card);border-radius:var(--radius);padding:26px;
  margin-bottom:20px;box-shadow:var(--shadow);border:1px solid var(--border)}
.section-title{font-size:17px;font-weight:700;color:var(--li-blue);
  padding-bottom:12px;border-bottom:2px solid var(--border);margin-bottom:18px}

/* Summary */
.sum-h3{font-size:15px;color:var(--li-blue);margin:20px 0 8px;font-weight:700}
.sum-h4{font-size:14px;color:var(--text);margin:12px 0 6px;font-weight:600}
.section p{line-height:1.75;color:#374151;margin-bottom:6px}

/* Summary-Tabellen */
.summary-table{width:100%;border-collapse:collapse;margin:14px 0;font-size:13px;border-radius:8px;overflow:hidden;box-shadow:var(--shadow)}
.summary-table thead{background:var(--li-blue);color:#fff}
.summary-table th{padding:9px 14px;text-align:left;font-weight:600;white-space:nowrap}
.summary-table td{padding:8px 14px;border-bottom:1px solid var(--border);color:#374151}
.summary-table tbody tr:nth-child(even){background:#f8fafc}
.summary-table tbody tr:hover{background:#eff6ff}

/* Badge */
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;
  border-radius:20px;color:#fff;font-size:12px;font-weight:600;white-space:nowrap}

/* Score bar */
.score-bar-wrap{display:inline-block;vertical-align:middle;
  width:90px;height:7px;background:#e2e8f0;border-radius:4px;margin-right:6px;overflow:hidden}
.score-bar{height:100%;border-radius:4px}
.score-val{font-size:11px;color:var(--muted);vertical-align:middle}

/* Sentiment chips */
.sent-grid{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}

/* Post card */
.post-card{border:1px solid var(--border);border-radius:var(--radius);
  padding:22px;margin-bottom:18px;transition:box-shadow .2s}
.post-card:hover{box-shadow:0 6px 18px rgba(0,0,0,.1)}
.post-header{display:flex;justify-content:space-between;align-items:flex-start;
  flex-wrap:wrap;gap:10px;margin-bottom:12px}
.post-num{background:var(--li-blue);color:#fff;border-radius:50%;width:30px;height:30px;
  display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex-shrink:0}
.author{font-weight:700;font-size:15px}
.author-title{font-size:12px;color:var(--muted);margin-top:2px;max-width:400px}
.metrics{display:flex;flex-wrap:wrap;gap:16px;margin:12px 0;font-size:13px;color:var(--muted)}
.metric{display:flex;align-items:center;gap:5px}
.topics{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.topic{background:#dbeafe;color:#1d4ed8;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:500}
.post-text{background:#f8fafc;border:1px solid var(--border);border-radius:8px;
  padding:14px;margin:12px 0;font-size:13px;line-height:1.75;
  white-space:pre-wrap;word-break:break-word;max-height:280px;overflow-y:auto}
.ai-box{background:#eff6ff;border-left:3px solid var(--li-blue);
  padding:12px 14px;border-radius:0 8px 8px 0;margin:12px 0;font-size:13px;line-height:1.6}
.comments-wrap{background:#f8fafc;border-radius:8px;padding:16px;margin-top:14px}
.comments-title{font-size:13px;font-weight:600;margin-bottom:10px;
  display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.comment{border-top:1px solid var(--border);padding:8px 0;font-size:13px;line-height:1.6}
.comment:first-of-type{border-top:none}
.comment b{color:var(--text)}
.more-comments{font-size:12px;color:var(--muted);margin-top:8px}
.notable{background:#fef9c3;border-radius:6px;padding:10px;
  margin-top:10px;font-size:13px;line-height:1.6}
.post-link{display:inline-block;margin-top:14px;font-size:13px;font-weight:500;
  color:var(--li-blue);border:1px solid var(--li-blue);border-radius:6px;
  padding:5px 12px;transition:all .2s}
.post-link:hover{background:var(--li-blue);color:#fff;text-decoration:none}

/* Footer */
.footer{text-align:center;color:var(--muted);font-size:12px;margin-top:40px;padding:20px}

@media print{
  body{background:#fff}
  .post-text{max-height:none;overflow:visible}
  .page{padding:0}
  .post-card:hover{box-shadow:none}
}
"""


def build_report(posts: list, summary: str, config: AnalysisConfig) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    total_likes = sum(p.likes for p in posts)
    total_comments = sum(p.comments for p in posts)
    total_reposts = sum(p.reposts for p in posts)

    # Sentiment-Verteilung
    sent_counts: dict[str, int] = {}
    for p in posts:
        sent_counts[p.sentiment_post] = sent_counts.get(p.sentiment_post, 0) + 1

    sent_html = "".join(
        f'<div style="text-align:center">{_sentiment_badge(s)}<br>'
        f'<small style="color:#64748b">{n}×</small></div>'
        for s, n in sorted(sent_counts.items())
    )

    def post_card(p, i: int) -> str:
        comments_html = ""
        if p.comments_list:
            items = "".join(
                f'<div class="comment"><b>{_esc(c["author"])}:</b> {_esc(c["text"])}</div>'
                for c in p.comments_list[:15]
            )
            more = (
                f'<div class="more-comments">+ {len(p.comments_list) - 15} weitere Kommentare</div>'
                if len(p.comments_list) > 15 else ""
            )
            notable = (
                f'<div class="notable">⭐ <b>Bemerkenswert:</b> {_esc(p.notable_comment)}</div>'
                if p.notable_comment else ""
            )
            comments_html = (
                f'<div class="comments-wrap">'
                f'<div class="comments-title">💬 Kommentare ({len(p.comments_list)})'
                f' &nbsp;{_sentiment_badge(p.sentiment_comments)}</div>'
                f'{items}{more}{notable}'
                f'</div>'
            )

        topics_html = "".join(f'<span class="topic">{_esc(t)}</span>' for t in p.main_topics)
        link_html = (
            f'<a class="post-link" href="{_esc(p.url)}" target="_blank" rel="noopener">'
            '→ Post auf LinkedIn öffnen ↗</a>'
        ) if p.url else ""

        return f"""
<div class="post-card">
  <div class="post-header">
    <div style="display:flex;gap:12px;align-items:flex-start">
      <div class="post-num">{i+1}</div>
      <div>
        <div class="author">{_esc(p.author)}</div>
        <div class="author-title">{_esc(p.author_title)}</div>
      </div>
    </div>
    <div style="text-align:right">
      {_sentiment_badge(p.sentiment_post)}
      <div style="margin-top:8px">{_score_bar(p.sentiment_score)}</div>
    </div>
  </div>

  <div class="metrics">
    <div class="metric">👍 <b>{p.likes:,}</b> Likes</div>
    <div class="metric">💬 <b>{p.comments:,}</b> Kommentare</div>
    <div class="metric">🔁 <b>{p.reposts:,}</b> Reposts</div>
    <div class="metric">📅 {_format_date(p.posted_at)}</div>
    <div class="metric">🏷️ via „{_esc(p.keyword)}"</div>
  </div>

  <div class="topics">{topics_html}</div>

  <div class="post-text">{_esc(p.text)}</div>

  <div class="ai-box">
    <b>🤖 KI-Zusammenfassung:</b> {_esc(p.summary)}
  </div>

  {comments_html}
  {link_html}
</div>"""

    posts_html = "\n".join(post_card(p, i) for i, p in enumerate(posts))

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LinkedIn Analyse – {_esc(config.keywords_str)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">

  <div class="header">
    <h1>🔍 LinkedIn Post-Analyse</h1>
    <div class="meta">
      <span>🏷️ <b>{_esc(config.keywords_str)}</b></span>
      <span>📅 Letzte {config.days} Tage</span>
      <span>🕐 {now}</span>
    </div>
  </div>

  <div class="stats">
    <div class="stat"><div class="num">{len(posts)}</div><div class="lbl">Posts (dedupliziert)</div></div>
    <div class="stat"><div class="num">{total_likes:,}</div><div class="lbl">Gesamte Likes</div></div>
    <div class="stat"><div class="num">{total_comments:,}</div><div class="lbl">Gesamte Kommentare</div></div>
    <div class="stat"><div class="num">{total_reposts:,}</div><div class="lbl">Gesamte Reposts</div></div>
    <div class="stat">
      <div class="sent-grid" style="justify-content:center">{sent_html}</div>
      <div class="lbl" style="margin-top:6px">Sentiment-Verteilung</div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">📊 Analyse &amp; Executive Summary</div>
    {_summary_to_html(summary)}
  </div>

  <div class="section">
    <div class="section-title">📋 Alle Posts im Detail ({len(posts)})</div>
    {posts_html}
  </div>

  <div class="footer">
    LinkedIn Post Analyzer &nbsp;|&nbsp; n8n-freie Docker-Lösung &nbsp;|&nbsp;
    Powered by Apify + Claude &nbsp;|&nbsp; {now}
  </div>

</div>
</body>
</html>"""
