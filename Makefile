.PHONY: dev dev-db dev-down test migrate run scope-fetch topic-refresh wp-no-article wd-no-label wd-no-description wiktionary-no-entry wikiquote-no-quotes wikisource-no-text commons-no-image commons-no-category

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

wd-no-label:
	FLASK_ENV=development python3 jobs/wd_no_label.py

wd-no-description:
	FLASK_ENV=development python3 jobs/wd_no_description.py

wiktionary-no-entry:
	FLASK_ENV=development python3 jobs/wiktionary_no_entry.py

wikiquote-no-quotes:
	FLASK_ENV=development python3 jobs/wikiquote_no_quotes.py

wikisource-no-text:
	FLASK_ENV=development python3 jobs/wikisource_no_text.py

commons-no-image:
	FLASK_ENV=development python3 jobs/commons_no_image.py

commons-no-category:
	FLASK_ENV=development python3 jobs/commons_no_category.py
