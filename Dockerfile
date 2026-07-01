FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libcairo2-dev \
       build-essential \
       pkg-config \
       libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build-Smoke-Test: rendert ein echtes Brett. Fehlt das renderPM-Backend
# (rlPyCairo), schlaegt der Build hier fehl statt spaeter still "ohne Brett".
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
