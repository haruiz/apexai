-include .env

.PHONY: help start

help:
	@echo "Targets:"
	@echo "  make start"
	@echo ""
	@echo "Configured values from .env:"
	@echo "  VBO_FILE=$(VBO_FILE)"
	@echo "  HOST=$(HOST)"
	@echo "  PORT=$(PORT)"
	@echo "  REPLAY_SPEED=$(REPLAY_SPEED)"
	@echo "  STREAM_INTERVAL=$(STREAM_INTERVAL)"
	@echo "  LOOP=$(LOOP)"
	@echo "  AUTOSTART=$(AUTOSTART)"
	@echo ""
	@echo "Example:"
	@echo "  make start VBO_FILE=./data/session.vbo STREAM_INTERVAL=5 LOOP=--loop"

start:
	uv run apexai-server \
		--vbo-file "$(VBO_FILE)" \
		--host "$(HOST)" \
		--port "$(PORT)" \
		--replay-speed "$(REPLAY_SPEED)" \
		$(if $(STREAM_INTERVAL),--stream-interval "$(STREAM_INTERVAL)",) \
		$(LOOP) \
		$(AUTOSTART)
