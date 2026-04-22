.PHONY: up stop down restart logs ps rebuild

up:
	docker compose up --build

stop:
	docker compose stop

down:
	docker compose stop

restart:
	docker compose stop
	docker compose up --build

rebuild:
	docker compose up -d --build

logs:
	docker compose logs -f

ps:
	docker compose ps
