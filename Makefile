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
DOCKER_BUILD = docker buildx build --load $(DOCKER_BUILD_ARGS)

.PHONY: install lint lint-docker test test-cov test-live test-ml hygiene lock lock-check \
	contract-check ci ca-bundle ingest synth docker-build docker-build-ml docker-test \
	docker-demo docker-check clean-ci

install:
	test -x .venv/bin/python || python3.12 -m venv .venv
	.venv/bin/python -m pip install -q -r requirements/dev.txt
	.venv/bin/python -m pip install -q --no-deps -e .

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

lock:
	@mkdir -p requirements
	$(UV_COMPILE) -o requirements/base.txt
	$(UV_COMPILE) --extra dev -o requirements/dev.txt
	$(UV_COMPILE) --extra ml -o requirements/ml.txt
	$(ML_INDEX) requirements/ml.txt

# Перекомпиляция поверх копий: uv сохраняет текущие версии, diff появляется, только
# если pyproject.toml и lock-файлы разошлись.
lock-check:
	@rm -rf $(BUILD)/lock && mkdir -p $(BUILD)/lock && cp requirements/*.txt $(BUILD)/lock/
	$(UV_COMPILE) -o $(BUILD)/lock/base.txt
	$(UV_COMPILE) --extra dev -o $(BUILD)/lock/dev.txt
	$(UV_COMPILE) --extra ml -o $(BUILD)/lock/ml.txt
	$(ML_INDEX) $(BUILD)/lock/ml.txt
	diff -u requirements $(BUILD)/lock && echo "lock-файлы соответствуют pyproject.toml"

contract-check:
	@rm -rf $(BUILD)/contract
	$(FM) contract export --out $(BUILD)/contract > /dev/null
	@for f in $(BUILD)/contract/*.json; do diff -u docs/contract/$$(basename $$f) $$f || exit 1; done
	@echo "схема в docs/contract совпадает с кодом"

# То же, что CI, кроме docker и gitleaks: быстрая проверка перед пушем.
ci: lint hygiene lock-check contract-check test-cov

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

docker-test:
	$(DOCKER_BUILD) --target test -t $(IMAGE):test .
	docker run --rm --network none $(IMAGE):test

docker-demo:
	FM_IMAGE=$(IMAGE):$(TAG) docker compose run --rm demo

docker-check:
	@mkdir -p $(CI_DIR)
	scripts/check_image.sh $(IMAGE):$(TAG) $(CI_DIR)/40-image.md

clean-ci:
	rm -rf $(BUILD)
