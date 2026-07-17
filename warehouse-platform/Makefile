# ============================================================
#  Autonomous Warehouse Platform Makefile
#  Local development orchestration tooling
# ============================================================

.PHONY: up down build logs seed clean status shell

up:
	docker-compose up -d

down:
	docker-compose down

build:
	docker-compose build --no-cache

logs:
	docker-compose logs -f $(service)

status:
	docker-compose ps

seed:
	@echo "Seeding default demo warehouse topology..."
	curl -X POST http://localhost:8001/api/v1/warehouses/a1b2c3d4-e5f6-7890-abcd-ef1234567890/seed-demo
	@echo "\nDemo warehouse seeded successfully!"

clean:
	docker-compose down -v
	rm -rf *.db
