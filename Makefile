-include .env

.PHONY: help setup start ui ui-dev ui-build sync deps build run-all deploy-apex deploy-dashboard deploy-all

help:
	@echo "Targets:"
	@echo "  make start"
	@echo "  make setup"
	@echo "  make sync"
	@echo "  make deps"
	@echo "  make build"
	@echo "  make run-all"
	@echo "  make ui"
	@echo "  make ui-build"
	@echo "  make deploy-apex"
	@echo "  make deploy-dashboard"
	@echo "  make deploy-all"
	@echo ""
	@echo "Configured values from .env:"
	@echo "  SOURCE=$(SOURCE)"
	@echo "  VBO_FILE=$(VBO_FILE)"
	@echo "  DBC_FILE=$(DBC_FILE)"
	@echo "  CAN_INTERFACE=$(CAN_INTERFACE)"
	@echo "  CAN_CHANNEL=$(CAN_CHANNEL)"
	@echo "  CAN_BITRATE=$(CAN_BITRATE)"
	@echo "  HOST=$(HOST)"
	@echo "  PORT=$(PORT)"
	@echo "  REPLAY_SPEED=$(REPLAY_SPEED)"
	@echo "  STREAM_INTERVAL=$(STREAM_INTERVAL)"
	@echo "  LOOP=$(LOOP)"
	@echo "  AUTOSTART=$(AUTOSTART)"
	@echo ""
	@echo "Example:"
	@echo "  make start STREAM_INTERVAL=5 LOOP=--loop"

sync:
	@echo "Pulling apexai..."
	git pull || echo "Warning: Could not pull apexai. Continuing..."
	@if [ -d "mobile/.git" ]; then \
		echo "Pulling mobile..."; cd mobile && git pull || echo "Warning: Could not pull mobile."; \
	else \
		echo "Mobile directory does not have a git repository. Skipping git pull for mobile."; \
	fi
	@if [ -d "dashboard/.git" ]; then \
		echo "Pulling dashboard..."; cd dashboard && git pull || echo "Warning: Could not pull dashboard."; \
	else \
		echo "dashboard directory does not have a git repository. Skipping git pull for dashboard."; \
	fi

deps:
	@echo "Installing backend dependencies (uv)..."
	uv sync
	@echo "Installing UI dependencies (npm)..."
	cd ui && npm install
	@if [ -d "dashboard/client" ]; then \
		echo "Installing dashboard client dependencies (npm)..."; \
		cd dashboard/client && npm install; \
	fi

build: ui-build
	@echo "Installing mobile dependencies..."
	@if [ -d "mobile" ]; then \
		cd mobile && ./gradlew assembleDebug || echo "Warning: mobile build failed."; \
	fi
	@echo "Building static dashboard data..."
	@if [ -d "dashboard/scripts" ]; then \
		cd dashboard && ./scripts/build_static_data.sh || echo "Warning: Static dashboard data build failed."; \
	fi

setup: sync deps build

run-all:
	@echo "Starting servers..."
	@lsof -ti :8000 -ti :3000 -ti :8761 -ti :8762 -ti :8763 | xargs kill -9 2>/dev/null || true
	@trap 'echo "\nStopping servers..."; kill %1 %2 %3 2>/dev/null || true; exit 0' SIGINT SIGTERM EXIT; \
	uv run apexai-server --autostart --loop & \
	uv run apexai-ui & \
	(cd dashboard/client && npm run dev) & \
	sleep 3; \
	if command -v open >/dev/null 2>&1; then \
		open http://127.0.0.1:3000; \
		open http://127.0.0.1:8000/state; \
		open http://127.0.0.1:5173; \
	fi; \
	wait

start:
	@lsof -ti :8000 -ti :3000 -ti :8761 -ti :8762 -ti :8763 | xargs kill -9 2>/dev/null || true
	@trap 'kill %1 2>/dev/null || true' SIGINT SIGTERM EXIT; \
	if [ -d "dashboard/client" ]; then (cd dashboard/client && npm run dev &); fi; \
	uv run apexai-server \
		$(if $(HOST),--host "$(HOST)",) \
		$(if $(PORT),--port "$(PORT)",) \
		$(if $(REPLAY_SPEED),--replay-speed "$(REPLAY_SPEED)",) \
		$(if $(STREAM_INTERVAL),--stream-interval "$(STREAM_INTERVAL)",) \
		$(LOOP) \
		$(AUTOSTART)

ui:
	@lsof -ti :3000 | xargs kill -9 2>/dev/null || true
	uv run apexai-ui

ui-dev: ui

ui-build:
	cd ui && npm run build:package

deploy-apex:
	gcloud run deploy apexai --source . --project the-need-for-speed --region us-central1 --allow-unauthenticated --memory 1Gi

deploy-dashboard:
	@if [ -d "dashboard/scripts" ]; then cd dashboard && ./scripts/build_static_data.sh; fi
	gcloud run deploy dashboard --source dashboard --project the-need-for-speed --region us-central1 --allow-unauthenticated --service-account="dashboard-sa@the-need-for-speed.iam.gserviceaccount.com"

deploy-all: deploy-apex deploy-dashboard
