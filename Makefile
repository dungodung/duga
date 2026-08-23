.PHONY: dev test run

dev:
	FLASK_ENV=development flask --app wsgi run --debug

test:
	pytest tests -v

run:
	gunicorn --bind 0.0.0.0:8000 wsgi:app
