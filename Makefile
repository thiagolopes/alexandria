lint:
	isort alexandria.py
	isort test.py
	pyflakes alexandria.py
	pyflakes test.py
