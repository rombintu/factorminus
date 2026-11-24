# Все проверки — цели этого Makefile. CI (.github/workflows/*.yml) только вызывает их.
# PY: .venv/bin/python, если есть (локально), иначе системный python (CI, контейнер).
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python)
FM ?= $(if $(wildcard .venv/bin/fm),.venv/bin/fm,fm)
IMAGE ?= factorminus
TAG ?= local
BUILD := build
CI_DIR := $(BUILD)/ci
# Порог покрытия: замер этапа 1.5 минус 2 п.п. Только растёт.
COV_MIN ?= 89
UV_COMPILE = $(PY) -m uv pip compile pyproject.toml --python-version 3.12 --universal \
	--quiet --no-header --emit-index-url --generate-hashes
# uv не пишет в lock-файл явный индекс torch CPU: добавляем строку, чтобы `pip install -r`
# находил torch==X+cpu. Хэши защищают от подмены пакета с дополнительного индекса.
ML_INDEX = $(PY) scripts/lock_extra_index.py
# build-system.requires (setuptools) — свой lock с хэшами: сборка пакета без build isolation
BUILD_COMPILE = $(PY) scripts/check_locks.py --build-requires | $(PY) -m uv pip compile - \
	--python-version 3.12 --universal --quiet --no-header --emit-index-url --generate-hashes
DOCKER_BUILD = docker buildx build --load $(DOCKER_BUILD_ARGS)
# bash: process substitution в contract-check, [[ ]] в release-guard
SHELL := /bin/bash

.PHONY: install install-deps lint lint-docker test test-cov test-live test-ml hygiene gitleaks \
	audit lock lock-check contract-check ci ci-summary release-notes release-guard ca-bundle \
	ingest synth \
	docker-build docker-build-ml docker-build-test docker-test docker-test-run docker-test-ml \
	docker-build-test-ml docker-test-ml-run \
	docker-demo docker-check clean-ci

install:
	test -x .venv/bin/python || python3.12 -m venv .venv
	.venv/bin/python -m pip install -q --require-hashes -r requirements/dev.txt -r requirements/build.txt
	.venv/bin/python -m pip install -q --no-deps --no-build-isolation -e .

# CI и контейнер: системный Python без .venv, версии строго из lock-файлов
install-deps:
	$(PY) -m pip install -q --require-hashes -r requirements/dev.txt -r requirements/build.txt
	$(PY) -m pip install -q --no-deps --no-build-isolation -e .

lint:
	$(PY) -m ruff check src tests scripts
	$(PY) -m ruff format --check src tests scripts

# actionlint и hadolint из закреплённых по digest контейнеров (нужен Docker)
ACTIONLINT_IMAGE := rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667
HADOLINT_IMAGE := ghcr.io/hadolint/hadolint:v2.15.1@sha256:32dac94127fd60b7b7e3fbfc65e1383b9b5e25c9bfd7b8536de7a539fe68a12d
GITLEAKS_IMAGE := ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
lint-docker:
	docker run --rm -v "$(CURDIR):/repo:ro" -w /repo $(ACTIONLINT_IMAGE) -color
	docker run --rm -i $(HADOLINT_IMAGE) hadolint --failure-threshold warning - < Dockerfile

test:
	$(PY) -m pytest -q

test-cov:
	@mkdir -p $(BUILD)
	$(PY) -m pytest -q --junitxml=$(BUILD)/junit.xml --cov=factorminus \
		--cov-report=xml:$(BUILD)/coverage.xml --cov-report=term:skip-covered \
		--cov-fail-under=$(COV_MIN)

test-live:
	$(PY) -m pytest -q --live -m live

test-ml:
	$(PY) -m pytest -q --ml -m ml

hygiene:
	@mkdir -p $(CI_DIR)
	$(PY) scripts/check_repo_hygiene.py --summary $(CI_DIR)/20-hygiene.md

# Вся история git (в CI checkout с fetch-depth: 0)
gitleaks:
	docker run --rm -v "$(CURDIR):/repo:ro" -e GIT_CONFIG_COUNT=1 \
		-e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/repo $(GITLEAKS_IMAGE) git /repo \
		--config /repo/.gitleaks.toml --redact --no-banner --exit-code 1

# Исключения: .github/pip-audit-ignore.txt, строка «ID # причина»
AUDIT_IGNORES = $(foreach id,$(shell sed -e 's/\#.*//' .github/pip-audit-ignore.txt 2>/dev/null),--ignore-vuln $(id))
audit:
	$(PY) -m pip_audit --disable-pip -r requirements/base.txt $(AUDIT_IGNORES)
	$(PY) -m pip_audit --disable-pip -r requirements/dev.txt $(AUDIT_IGNORES)
	$(PY) -m pip_audit --disable-pip -r requirements/ml.txt $(AUDIT_IGNORES)

lock:
	@mkdir -p requirements
	$(UV_COMPILE) -o requirements/base.txt
	$(UV_COMPILE) --extra dev -o requirements/dev.txt
	$(UV_COMPILE) --extra ml -o requirements/ml.txt
	$(ML_INDEX) requirements/ml.txt
	$(BUILD_COMPILE) -o requirements/build.txt

# Перекомпиляция поверх копий: uv сохраняет текущие версии, diff появляется, только
# если pyproject.toml и lock-файлы разошлись.
lock-check:
	@rm -rf $(BUILD)/lock && mkdir -p $(BUILD)/lock && cp requirements/*.txt $(BUILD)/lock/
	$(UV_COMPILE) -o $(BUILD)/lock/base.txt
	$(UV_COMPILE) --extra dev -o $(BUILD)/lock/dev.txt
	$(UV_COMPILE) --extra ml -o $(BUILD)/lock/ml.txt
	$(ML_INDEX) $(BUILD)/lock/ml.txt
	$(BUILD_COMPILE) -o $(BUILD)/lock/build.txt
	diff -u requirements $(BUILD)/lock && echo "lock-файлы соответствуют pyproject.toml"
	$(PY) scripts/check_locks.py requirements/base.txt requirements/dev.txt requirements/ml.txt

contract-check:
	@rm -rf $(BUILD)/contract
	$(FM) contract export --out $(BUILD)/contract > /dev/null
	@for f in $(BUILD)/contract/*.json; do diff -u docs/contract/$$(basename $$f) $$f || exit 1; done
	@diff -u <(cd docs/contract && ls *.schema.json) <(cd $(BUILD)/contract && ls *.schema.json) \
		|| (echo "набор схем в docs/contract и в коде разный"; exit 1)
	@echo "схема в docs/contract совпадает с кодом"

# То же, что CI, кроме docker и gitleaks: быстрая проверка перед пушем.
ci: lint hygiene lock-check contract-check test-cov

ci-summary:
	$(PY) scripts/ci_summary.py --build $(BUILD)

# Текст GitHub Release: RELEASE_TAG=v0.1.5 make release-notes (тег только из окружения)
release-notes:
	@mkdir -p $(BUILD)
	$(PY) scripts/release_notes.py --tag "$$RELEASE_TAG" > $(BUILD)/release.md

# Перед публикацией по тегу: формат vX.Y.Z и коммит уже в origin/main
release-guard:
	@[[ "$$RELEASE_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$$ ]] \
		|| { echo "тег '$$RELEASE_TAG': ожидается vX.Y.Z"; exit 1; }
	@git merge-base --is-ancestor HEAD origin/main \
		|| { echo "коммит тега не входит в main: публикация отменена"; exit 1; }
	@echo "тег $$RELEASE_TAG на коммите из main"

ca-bundle:
	$(PY) scripts/build_ca_bundle.py --out data/ca/ru-bundle.pem

ingest:
	$(FM) ingest --mode record

synth:
	$(FM) synth generate --seed 42 --out tests/fixtures/synthetic
	$(FM) synth load

docker-build:
	@mkdir -p $(CI_DIR)
	scripts/timed.sh $(CI_DIR)/build-runtime.txt $(DOCKER_BUILD) --target runtime -t $(IMAGE):$(TAG) .

docker-build-ml:
	@mkdir -p $(CI_DIR)
	scripts/timed.sh $(CI_DIR)/build-runtime-ml.txt $(DOCKER_BUILD) --target runtime-ml -t $(IMAGE):$(TAG)-ml .

docker-build-test:
	$(DOCKER_BUILD) --target test -t $(IMAGE):test .

# Тесты в контейнере без сети, от непривилегированного пользователя образа
docker-test-run:
	docker run --rm --network none $(IMAGE):test

docker-test: docker-build-test docker-test-run

# ML smoke в образе test-ml (runtime-ml + pytest): веса уже внутри, сеть отключена
docker-build-test-ml:
	$(DOCKER_BUILD) --target test-ml -t $(IMAGE):test-ml .

docker-test-ml-run:
	docker run --rm --network none $(IMAGE):test-ml

docker-test-ml: docker-build-test-ml docker-test-ml-run

docker-demo:
	FM_IMAGE=$(IMAGE):$(TAG) docker compose run --rm demo

docker-check:
	@mkdir -p $(CI_DIR)
	scripts/check_image.sh $(IMAGE):$(TAG) $(CI_DIR)/40-image.md

clean-ci:
	rm -rf $(BUILD)
