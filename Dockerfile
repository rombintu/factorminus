FROM python:3.12-slim
ENV UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never PATH="/app/.venv/bin:$PATH"
WORKDIR /app
# uv подключается только на время сборки и в образ не попадает.
# Слой зависимостей пересобирается только при смене pyproject.toml или uv.lock.
COPY pyproject.toml uv.lock ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.9,source=/uv,target=/bin/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.9,source=/uv,target=/bin/uv \
    uv sync --frozen --no-dev --no-editable \
    && useradd --create-home --uid 1000 app && mkdir data && chown app data
USER app
CMD ["fm", "demo"]
