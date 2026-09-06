.PHONY: check test setup

check: ## static shell checks (bash -n + shellcheck)
	./scripts/check.sh

setup: ## install/update Homebrew, CLT and Ansible, then run the provision playbook
	./bootstrap.sh

test: ## stub-based playbook tests (provisions .test-venv as needed)
	./scripts/ensure_test_env.sh
	./.test-venv/bin/python -m pytest tests/ -q
