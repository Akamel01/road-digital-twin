# Control API image. Built and run on the box by deploy/compose.yaml; nothing here touches sme_* containers.
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.11-slim

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    TWIN_RUNS=/data/twin-runs

COPY --from=uv /uv /uvx /usr/local/bin/

RUN groupadd --system --gid 10001 twin \
 && useradd --system --uid 10001 --gid twin --home /app twin

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY twin ./twin
RUN uv sync --frozen --no-dev

RUN mkdir -p /data/twin-runs && chown twin:twin /data/twin-runs
USER twin

EXPOSE 8090
CMD ["twin", "serve", "--host", "0.0.0.0", "--port", "8090", "--store", "/data/twin-runs"]
