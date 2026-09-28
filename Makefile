.PHONY: check test setup verify

check: ## static shell checks (bash -n + shellcheck)
	./scripts/check.sh

setup: ## install/update Homebrew, CLT and Ansible, then run the provision playbook
	./bootstrap.sh

test: ## stub-based playbook tests (provisions .test-venv as needed)
	./scripts/ensure_test_env.sh
	./.test-venv/bin/python -m pytest tests/ -q

verify: ## real-machine smoke checks after bootstrap (never installs)
	./scripts/verify.sh
