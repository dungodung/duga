.PHONY: dev dev-db dev-down test migrate run scope-fetch topic-refresh wp-no-article

dev:
	FLASK_ENV=development flask --app wsgi run --debug

dev-db:
	docker compose up -d db

dev-down:
	docker compose down

test:
	pytest tests -v

migrate:
	FLASK_ENV=development flask --app wsgi db upgrade

run:
	gunicorn --bind 0.0.0.0:8000 wsgi:app

scope-fetch:
	FLASK_ENV=development python3 jobs/scope_fetch.py

topic-refresh:
	FLASK_ENV=development python3 jobs/topic_refresh.py

wp-no-article:
	FLASK_ENV=development python3 jobs/wp_no_article.py
