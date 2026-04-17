FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

WORKDIR /extension

# Install build dependencies for packages that need compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    python3-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN uv venv /opt/venv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH=/opt/venv/bin:$PATH

FROM base AS build

COPY . .

RUN uv sync --frozen --no-cache --no-dev

FROM build AS dev

RUN uv sync --frozen --no-cache --dev

CMD ["swoext", "run"]

FROM build AS prod

RUN rm -rf tests/

RUN groupadd -r appuser && useradd -r -g appuser -m -d /home/appuser appuser && \
    mkdir -p /home/appuser/.cache/uv && \
    chown -R appuser:appuser /extension /opt/venv /home/appuser

ENV UV_CACHE_DIR=/home/appuser/.cache/uv

USER appuser

CMD ["swoext", "run", "--no-color"]
