.PHONY: help test package clean

help:
	@echo "Targets:"
	@echo "  make test     - Run mechanical test suite for the bundled script"
	@echo "  make package  - Build .skill bundle for distribution"
	@echo "  make clean    - Remove generated artifacts"

test:
	python3 scripts/test_obsidian.py

package:
	python3 -m scripts.package_skill .
	@echo ""
	@echo "Install via: npx skills add <repo> -g -a claude-code -a gemini-cli -a codex -a pi -y"

clean:
	rm -f obsidian-skill.skill
	find . -name __pycache__ -type d -exec rm -rf {} +
	find . -name '*.pyc' -delete
