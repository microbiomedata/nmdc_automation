
test:
	poetry run pytest --cov-report term-missing --cov=nmdc_automation -m "not (integration or jaws or jaws_submit)"

test-jaws:
	poetry run pytest -m "jaws" ./tests

test-jaws-submit:
	poetry run pytest -m "jaws_submit" ./tests


test-integration:
	poetry run pytest -m "integration" ./tests