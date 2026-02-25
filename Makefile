lint:
	@isort *.py
	@pyflakes *.py
	@mypy *.py
