# syntax=docker/dockerfile:1.7
# Один Dockerfile для CI и запуска. Цели:
#   runtime     — CLI, nightly, демо, позже API (по умолчанию);
#   runtime-ml  — runtime + laya (torch CPU) + веса laya, скачанные при сборке;
#   test        — runtime + dev-зависимости + tests/: make docker-test;
#   test-ml     — runtime-ml + dev-зависимости + ML-тесты: make docker-test-ml.
# Токена и .env в образе нет: они передаются только при запуске (compose env_file).

ARG PYTHON_IMAGE=python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b

# --- общая база: системный Python, без кэшей ---
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH
WORKDIR /app

# --- зависимости: отдельный слой, меняется только с lock-файлом ---
FROM base AS venv-base
COPY requirements/base.txt /tmp/requirements/base.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
    && pip install --require-hashes -r /tmp/requirements/base.txt

FROM base AS venv-ml
COPY requirements/ml.txt /tmp/requirements/ml.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
    && pip install --require-hashes -r /tmp/requirements/ml.txt

FROM base AS venv-dev
COPY requirements/dev.txt /tmp/requirements/dev.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
    && pip install --require-hashes -r /tmp/requirements/dev.txt

# --- пакет factorminus: колесо собирается отдельно, в образ ставится без исходников ---
FROM venv-base AS wheel
COPY pyproject.toml README.md LICENSE /src/
COPY src /src/src
RUN --mount=type=cache,target=/root/.cache/pip \
    pip wheel --no-deps --wheel-dir /wheels /src

# --- CA-бандл: certifi + certs/*.pem со сверкой отпечатков (ошибка при подмене) ---
FROM venv-base AS ca
COPY certs /src/certs
COPY scripts/build_ca_bundle.py /src/scripts/build_ca_bundle.py
RUN python /src/scripts/build_ca_bundle.py --certs /src/certs --out /opt/factorminus/ca/ru-bundle.pem

# --- веса laya: скачиваются при сборке, холодный старт не ходит в сеть ---
FROM venv-ml AS laya-weights
# Все три чекпойнта (english, multilingual, typed-decisions) — подпапки одного репозитория
# convaiinnovations/laya (laya.router.BUNDLE_REPO); Router читает их из кэша huggingface_hub
# в $HF_HOME/hub. Скачиваем снимок без загрузки моделей в память (сборке хватает 4 ГБ RAM).
# Ревизия закреплена, чтобы веса в образе не менялись между сборками.
ARG LAYA_REVISION=fd4f9dbcf4fde222fd43174bdd4c3b08b789e4e1
ENV HF_HOME=/opt/hf LAYA_REVISION=${LAYA_REVISION}
RUN python -c "import os; from huggingface_hub import snapshot_download; from laya.router import BUNDLE_REPO; print(snapshot_download(BUNDLE_REPO, revision=os.environ['LAYA_REVISION']))" \
    && rm -rf /opt/hf/xet /opt/hf/hub/.locks
# процесс в runtime-ml не root: кэш весов только для чтения, но читаемый всеми
RUN chmod -R a+rX,go-w /opt/hf

# --- файлы из git, которые нужны во время работы (только чтение) ---
FROM scratch AS app-files
COPY data/*.yaml /app/data/
COPY tests/fixtures/synthetic /app/tests/fixtures/synthetic
COPY --from=ca /opt/factorminus/ca /opt/factorminus/ca

# --- runtime ---
FROM base AS runtime
ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="factorminus" \
      org.opencontainers.image.description="Фактор-минус: CLI, загрузка данных, демо на синтетике" \
      org.opencontainers.image.source="https://github.com/rombintu/factorminus" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"
ENV PIP_NO_CACHE_DIR=1 \
    FM_HOME=/app \
    FM_DATA_DIR=/var/lib/factorminus \
    TINVEST_CA_BUNDLE=/opt/factorminus/ca/ru-bundle.pem
RUN groupadd --system --gid 10001 fm \
    && useradd --system --uid 10001 --gid fm --no-create-home --home-dir /nonexistent \
       --shell /usr/sbin/nologin fm \
    && install -d -o 10001 -g 10001 -m 0750 /var/lib/factorminus
COPY --from=venv-base /opt/venv /opt/venv
COPY --from=app-files /app /app
COPY --from=app-files /opt/factorminus /opt/factorminus
RUN --mount=type=bind,from=wheel,source=/wheels,target=/wheels \
    pip install --no-deps --no-index /wheels/*.whl
USER 10001:10001
ENTRYPOINT ["fm"]
CMD ["--help"]

# --- runtime-ml: то же + laya, torch CPU и веса ---
FROM base AS runtime-ml
ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="factorminus-ml" \
      org.opencontainers.image.description="Фактор-минус с laya (torch CPU) и весами модели" \
      org.opencontainers.image.source="https://github.com/rombintu/factorminus" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"
ARG LAYA_REVISION=fd4f9dbcf4fde222fd43174bdd4c3b08b789e4e1
ENV PIP_NO_CACHE_DIR=1 \
    FM_HOME=/app \
    FM_DATA_DIR=/var/lib/factorminus \
    TINVEST_CA_BUNDLE=/opt/factorminus/ca/ru-bundle.pem \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    LAYA_REVISION=${LAYA_REVISION}
RUN groupadd --system --gid 10001 fm \
    && useradd --system --uid 10001 --gid fm --no-create-home --home-dir /nonexistent \
       --shell /usr/sbin/nologin fm \
    && install -d -o 10001 -g 10001 -m 0750 /var/lib/factorminus
COPY --from=venv-ml /opt/venv /opt/venv
COPY --from=laya-weights /opt/hf /opt/hf
COPY --from=app-files /app /app
COPY --from=app-files /opt/factorminus /opt/factorminus
RUN --mount=type=bind,from=wheel,source=/wheels,target=/wheels \
    pip install --no-deps --no-index /wheels/*.whl
USER 10001:10001
ENTRYPOINT ["fm"]
CMD ["--help"]

# --- test: pytest в контейнере (сеть в тестах заблокирована conftest) ---
FROM runtime AS test
USER 0
# venv-dev содержит те же закреплённые версии base плюс dev; factorminus из runtime остаётся
COPY --from=venv-dev /opt/venv /opt/venv
COPY pyproject.toml /app/pyproject.toml
COPY certs /app/certs
COPY scripts /app/scripts
COPY tests /app/tests
COPY docs/contract /app/docs/contract
USER 10001:10001
ENTRYPOINT []
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

# --- test-ml: ML smoke в runtime-ml без сети (веса уже в образе) ---
FROM runtime-ml AS test-ml
USER 0
# версии общих пакетов в dev.txt и ml.txt совпадают (один pyproject, uv universal)
COPY requirements/dev.txt /tmp/requirements/dev.txt
RUN pip install --require-hashes -r /tmp/requirements/dev.txt
COPY pyproject.toml /app/pyproject.toml
COPY tests/conftest.py tests/test_ml_smoke.py /app/tests/
USER 10001:10001
ENTRYPOINT []
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--ml", "-m", "ml"]
