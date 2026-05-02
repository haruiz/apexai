-include .env

.PHONY: help start ui ui-dev ui-build

help:
	@echo "Targets:"
	@echo "  make start"
	@echo "  make ui"
	@echo "  make ui-build"
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
	@echo "  make start SOURCE=vbo VBO_FILE=./data/session.vbo STREAM_INTERVAL=5 LOOP=--loop"
	@echo "  make start SOURCE=can DBC_FILE=./data/vehicle.dbc CAN_INTERFACE=socketcan CAN_CHANNEL=vcan0"

start:
	uv run apexai-server \
		--source "$(or $(SOURCE),vbo)" \
		--vbo-file "$(VBO_FILE)" \
		$(if $(DBC_FILE),--dbc-file "$(DBC_FILE)",) \
		--can-interface "$(or $(CAN_INTERFACE),socketcan)" \
		--can-channel "$(or $(CAN_CHANNEL),can0)" \
		$(if $(CAN_BITRATE),--can-bitrate "$(CAN_BITRATE)",) \
		--host "$(HOST)" \
		--port "$(PORT)" \
		--replay-speed "$(REPLAY_SPEED)" \
		$(if $(STREAM_INTERVAL),--stream-interval "$(STREAM_INTERVAL)",) \
		$(LOOP) \
		$(AUTOSTART)

ui:
	uv run apexai-ui

ui-dev: ui

ui-build:
	cd ui && npm run build:package
