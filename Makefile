up:
	docker compose -f docker-compose.yml up -d
down:
	docker compose -f docker-compose.yml down

build:
	docker compose -f docker-compose.yml build

superuser:
	docker exec -it web poetry run python manage.py createsuperuser

migrate:
	docker exec -it web poetry run python manage.py migrate

migrations:
	docker exec -it web poetry run python manage.py makemigrations

logs:
	docker container logs web