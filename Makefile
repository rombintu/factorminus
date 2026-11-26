.PHONY: lint test demo docker

lint:
	uv run ruff check
	uv run ruff format --check

test:
	uv run pytest -q

demo:
	uv run fm demo

docker:
	docker build -t factorminus .
	docker run --rm factorminus fm demo
