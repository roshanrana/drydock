# Thin wrapper; the real logic is in scripts/check.py so Windows hosts without GNU make
# can run `uv run python scripts/check.py` and get the identical gate.
.PHONY: check lint type test bench bench-check card card-check demo serve mcp

check:
	uv run python scripts/check.py

lint:
	uv run ruff check . && uv run ruff format --check .

type:
	uv run mypy drydock

test:
	uv run pytest --cov=drydock --cov-report=term-missing --cov-fail-under=80

bench:
	uv run drydock bench

bench-check: bench
	git diff --exit-code -- metrics/headline.json

card: bench
	uv run python metrics/render.py

card-check:
	uv run python metrics/render.py --check

demo:
	uv run drydock build acme-treasury --provider fake

serve:
	uv run drydock serve

mcp:
	uv run drydock mcp
