.PHONY: check test

check: ## static shell checks (bash -n + shellcheck)
	./scripts/check.sh

test: ## stub-based playbook tests (provisions .test-venv as needed)
	./scripts/ensure_test_env.sh
	./.test-venv/bin/python -m pytest tests/ -q
