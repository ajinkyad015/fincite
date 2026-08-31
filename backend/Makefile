run:
	echo "Running in local mode."
	docker compose create db
	docker compose start db
	uv run start

run_docker:
	echo "Running in local mode with docker."
	docker compose up

migrate:
	echo "Running migrations."
	docker compose create db
	docker compose start db
	uv run python -m alembic upgrade head
	# workaround for having PGVector create its tables
	uv run python -m scripts.build_vector_tables

refresh_db:
	# First ask for confirmation.
	@echo -n "Are you sure you want to refresh the local database? This will delete all data in your local db. [Y/n] "; \
	read ans; \
	if [ $${ans:-'N'} = 'Y' ]; then make confirmed_refresh_db; else echo "Aborting."; fi

confirmed_refresh_db:
	echo "Refreshing database."
	docker compose down db
	docker volume rm backend_postgres_data
	make migrate

test:
	uv run python -m pytest tests/

chat:
	uv run python -m scripts.chat_llama

