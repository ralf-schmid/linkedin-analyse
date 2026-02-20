FROM python:3.12-slim

# Arbeitsverzeichnis
WORKDIR /srv

# Dependencies installieren (Layer-Caching: requirements zuerst)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungscode kopieren
COPY app/ ./app/

# Output-Verzeichnis für CLI-Modus
RUN mkdir -p /output

# Port freigeben
EXPOSE 8080

# Standard: Web-Server starten
# Für CLI-Modus: docker run --rm ... python -m app.main analyze --keywords "..." --output /output/report.html
CMD ["python", "-m", "app.main", "serve"]
