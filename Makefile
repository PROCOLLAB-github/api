up:
	docker compose -f docker-compose.yml up -d
down:
	docker compose -f docker-compose.yml down

run-local:
	poetry run daphne -b 0.0.0.0 -p 8000 procollab.asgi:application
