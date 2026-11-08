test:
	uv run pytest -q

itest:
	uv run pytest -q -m itest

.PHONY: test itest
