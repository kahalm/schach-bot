# --- Build-Stage: Abhaengigkeiten bauen (pycairo kompiliert gegen libcairo2-dev) ---
FROM python:3.13-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libcairo2-dev \
       build-essential \
       pkg-config \
       libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Exakt die Versionen + Hashes aus requirements.lock (pip-compile --generate-hashes);
# ein neues Release auf PyPI kommt so nur per bewusstem Lock-Commit ins Image.
# In ein venv, das die Laufzeit-Stage fertig uebernimmt.
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# --- Laufzeit: ohne Compiler und -dev-Pakete, nur die cairo-Laufzeitbibliothek ---
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /app

COPY . .

# Build-Smoke-Test: rendert ein echtes Brett. Fehlt das renderPM-Backend
# (rlPyCairo) oder die cairo-Laufzeitbibliothek, schlaegt der Build hier fehl
# statt spaeter still "ohne Brett".
RUN python tests/test_rendering.py

RUN useradd -m botuser && chown -R botuser:botuser /app
USER botuser

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "healthcheck.py"]

ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA
ARG GIT_REF=
ENV GIT_REF=$GIT_REF

CMD ["python", "bot.py"]
