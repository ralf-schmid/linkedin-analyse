# LinkedIn Post Analyzer

KI-gestützte LinkedIn-Post-Analyse mit Sentiment-Bewertung und Executive Summary.  
Gebaut mit **FastAPI + Apify + Claude** – ohne Fixkosten, pay-per-use.

## Features

- 🔍 **Keyword-Scraping** via Apify (LinkedIn Posts der letzten 7 / 14 / 30 Tage)
- 🧹 **Automatische Deduplizierung** über mehrere Suchbegriffe
- 🤖 **Sentiment-Analyse** je Post + Kommentare (Claude Haiku)
- 📊 **Executive Summary** mit Stimmungsbild & Meinungsführern (Claude Sonnet)
- 📄 **HTML-Report** – direkt im Browser, zum Download oder lokal gespeichert
- 🖥️ **Web-UI** – Formular im Browser, Echtzeit-Fortschritt via SSE
- ⌨️ **CLI-Modus** – vollständig skriptbar für Automatisierung

## Kosten (pay-per-use, keine Fixkosten)

| Komponente | Kosten / Auswertung |
|---|---|
| Apify LinkedIn Scraping (100 Posts) | ~0,50–1,50 € |
| Claude Haiku – Sentiment je Post | ~0,10–0,30 € |
| Claude Sonnet – Executive Summary | ~0,05–0,15 € |
| **Gesamt** | **~0,65–2,00 €** |

## Schnellstart

### 1. Repository klonen & Umgebungsvariablen setzen

```bash
git clone https://github.com/DEIN-USERNAME/linkedin-analyzer.git
cd linkedin-analyzer
cp .env.example .env
# .env öffnen und API-Keys eintragen
```

### 2. Web-Server starten

```bash
docker compose up -d
```

Öffne `http://localhost:8080` im Browser.

### 3. CLI-Modus (einmalige Auswertung → HTML-Datei)

```bash
docker run --rm \
  --env-file .env \
  -v $(pwd)/output:/output \
  linkedin-analyzer:latest \
  python -m app.main analyze \
  --keywords "Agentic AI, KI Plattform" \
  --days 7 \
  --max-posts 30 \
  --output /output/analyse_2025-05.html
```

Der Report liegt danach in `./output/analyse_2025-05.html`.

## Einrichtung

### API-Keys

**Apify**
1. Account anlegen: https://apify.com (kostenloser Einstieg mit Credits)
2. `Settings → Integrations → API Tokens` → Token kopieren
3. In `.env`: `APIFY_TOKEN=apify_api_...`

**Anthropic**
1. Console: https://console.anthropic.com → API Keys → Neuen Key erstellen
2. In `.env`: `ANTHROPIC_API_KEY=sk-ant-...`

### LinkedIn Session-Cookie (Apify)

Apify benötigt einen LinkedIn-Session-Cookie für das Scraping:
1. Im Browser auf linkedin.com einloggen
2. DevTools öffnen (`F12`) → Application → Cookies → `li_at` kopieren
3. Im Apify-Dashboard beim Actor als Input-Cookie hinterlegen

Der Cookie hält mehrere Wochen. Apify kümmert sich um die Rotation.

### Alternativer Apify Actor

Falls `curious_coder~linkedin-post-search-scraper` nicht mehr verfügbar:

```env
APIFY_ACTOR=jiri.spilka~linkedin-post-scraper
```

Beide Actors im [Apify Marketplace](https://apify.com/store) suchen.

## GitHub Actions / CI-CD

Der Workflow in `.github/workflows/deploy.yml` baut das Docker-Image bei jedem Push auf `main` und deployed automatisch auf deinen Server.

### Secrets in GitHub eintragen

| Secret | Wert |
|---|---|
| `DEPLOY_HOST` | IP oder Hostname deines Servers |
| `DEPLOY_USER` | SSH-Benutzername |
| `DEPLOY_SSH_KEY` | Privater SSH-Key (ohne Passphrase) |

Die API-Keys (`APIFY_TOKEN`, `ANTHROPIC_API_KEY`) werden **nicht** als GitHub Secrets gesetzt – sie liegen als `.env`-Datei direkt auf dem Server und werden nie committet.

### Server vorbereiten

```bash
# Auf dem Server (einmalig)
git clone https://github.com/DEIN-USERNAME/linkedin-analyzer.git ~/linkedin-analyzer
cd ~/linkedin-analyzer
cp .env.example .env && nano .env   # API-Keys eintragen
```

Danach übernimmt der GitHub Actions Workflow das Deploy automatisch.

## Projektstruktur

```
linkedin-analyzer/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI App + CLI-Entrypoint
│   ├── analyzer.py      # Apify + Claude Logik, Datenmodelle
│   ├── report.py        # HTML-Report-Generator
│   └── templates/
│       └── index.html   # Web-UI
├── output/              # CLI-Reports (gitignored)
├── .github/
│   └── workflows/
│       └── deploy.yml   # CI/CD Pipeline
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

## Lokale Entwicklung (ohne Docker)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env && nano .env  # Keys eintragen

# Server mit Auto-Reload
uvicorn app.main:app --reload --port 8080
```

## Lizenz

MIT
