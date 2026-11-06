# One image for every service of docker-compose.yml: the scheduled runs,
# the Telegram listener and the web app only differ by their command.
FROM python:3.12-slim

ARG LLM_CLI_VERSION=2.1.318
ARG SUPERCRONIC_VERSION=v0.2.51
ARG SUPERCRONIC_SHA256=cc232108374e8e2b537045f2d5eaa1229f619db314c3ba6a14d38b35dc0aa123

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    TZ=Europe/Paris

# Node.js runs the headless LLM CLI used for triage and letters;
# supercronic replaces the systemd timers inside the container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl nodejs npm tzdata \
    && npm install -g "@anthropic-ai/claude-code@${LLM_CLI_VERSION}" \
    && curl -fsSL -o /usr/local/bin/supercronic \
       "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && echo "${SUPERCRONIC_SHA256}  /usr/local/bin/supercronic" | sha256sum -c - \
    && chmod +x /usr/local/bin/supercronic \
    && npm cache clean --force \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir "poetry==2.5.1" \
    && poetry install --only main --no-root --no-interaction \
    && pip uninstall -y poetry

COPY intern_radar ./intern_radar
COPY config/companies.yaml config/profile.example.yaml ./config/
COPY deploy/crontab ./deploy/crontab
COPY README.md ./
RUN pip install --no-cache-dir --no-deps .

# config/profile.yaml (secrets), data/ and logs/ are mounted at run time.
VOLUME ["/app/data", "/app/logs"]
EXPOSE 8787

CMD ["supercronic", "/app/deploy/crontab"]
