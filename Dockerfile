# TVF Lead Engine -- the review UI and the operator tooling in one image.
#
# Deliberately boring. python:slim, pip install, copy the source. There is no
# node stage, no asset build and nothing to compile, because the frontend is
# three static files (see app/main.py for why). A build that cannot fail in
# interesting ways is worth a lot four days before a deadline.
#
# The image also carries tools/ so enrichment and export can be run inside the
# container -- `docker compose run --rm app python tools/enrich_sitescrape.py`
# -- which is what makes the cloud step a lift-and-shift rather than a rewrite.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# psycopg2-binary needs no build toolchain; curl is here for the healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/    ./app/
COPY tools/  ./tools/
COPY sql/    ./sql/
COPY config/ ./config/
# the files emails attach (outreach.attachments: LCX Services' deck); the drafts record them and the
# sender reads them from here, so the image must carry them
COPY docs/decks/ ./docs/decks/

# Run as a non-root user. This container talks to a database holding contact
# details for real people; root is not the identity that should hold that.
# uid 1000 specifically: Hugging Face Spaces run containers as that user,
# and files owned by anyone else are unwritable there (ops logs).
RUN useradd --create-home --uid 1000 tvf && chown -R tvf:tvf /srv
USER tvf

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-8000}/api/health || exit 1

# One worker: the workload is a handful of reviewers, and a single process
# keeps the psycopg2 pool honest. Scale with replicas, not workers, if ever.
# Shell form so the port follows $PORT when a platform sets one (Render
# sets 10000, Hugging Face Spaces 7860 unless told 8000); 8000 otherwise,
# which is what compose and Caddy expect. exec keeps uvicorn as PID 1.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
