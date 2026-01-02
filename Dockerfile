FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

WORKDIR /extension

RUN uv venv /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:$PATH

FROM base AS build

COPY . /extension

RUN uv sync --frozen --no-cache --all-groups --active

FROM build AS dev

CMD ["swoext", "run"]

FROM build AS prod

RUN groupadd -r appuser && useradd -r -g appuser appuser && \
    chown -R appuser:appuser /extension /opt/venv

USER appuser

RUN rm -rf tests/

CMD ["swoext", "run", "--no-color"]
