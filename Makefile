# Developer shortcuts. Windows users without `make` can run the commands directly.
MODEL ?= mock

.PHONY: install test lint format eval examples serve doctor build docker clean check

check: lint test eval

install:
	uv sync --all-extras

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check . --fix

eval:
	uv run agentcore eval --suite examples/evals/calculator_suite.yaml --model $(MODEL)

examples:
	uv run python examples/calculator_agent.py --model $(MODEL)
	uv run python examples/rag_qa.py --model $(MODEL)
	uv run python examples/workflow_graph.py
	uv run python examples/multi_agent.py --model $(MODEL)

serve:
	uv run agentcore serve --model $(MODEL)

doctor:
	uv run agentcore doctor --model $(MODEL)

build:
	uv build

docker:
	docker compose up --build

clean:
	rm -rf .agentcore .pytest_cache .ruff_cache dist build workspace
