"""FastAPI routes and streaming endpoints for telemetry replay."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from .broadcaster import Broadcaster
from .config import ServerConfig
from .schemas import (
    ReplayState,
    SeekRequest,
    SpeedUpdate,
    StreamIntervalUpdate,
    TelemetryPacket,
    TelemetryTracePoint,
)
from .telemetry_sources import TelemetrySource

logger = logging.getLogger(__name__)


def create_app(config: ServerConfig, source: TelemetrySource, broadcaster: Broadcaster) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Runtime server configuration.
        source: Telemetry source used by HTTP control routes.
        broadcaster: Telemetry broadcaster used by streaming routes.

    Returns:
        Configured FastAPI application instance.
    """

    app = FastAPI(title="ApexAI Telemetry Streaming Server")
    app.state.config = config
    app.state.source = source
    app.state.broadcaster = broadcaster

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost",
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "https://dashboard-812524149286.us-central1.run.app",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _startup() -> None:
        """Start replay during application startup when configured."""

        logger.info("server started with source=%s samples=%s", config.source, source.total_samples)
        if config.autostart:
            await source.play()

    @app.get("/health")
    async def health() -> dict[str, object]:
        """Return a lightweight server health payload."""

        state = source.state()
        return {"status": "ok", "source": state.source, "samples": source.total_samples, "replay": state.status}

    @app.get("/state", response_model=ReplayState)
    async def state() -> ReplayState:
        """Return the current replay state."""

        return source.state()

    @app.post("/replay/start", response_model=ReplayState)
    async def replay_start() -> ReplayState:
        """Start or resume telemetry replay."""

        return await source.play()

    @app.post("/replay/pause", response_model=ReplayState)
    async def replay_pause() -> ReplayState:
        """Pause telemetry replay."""

        return await source.pause()

    @app.post("/replay/stop", response_model=ReplayState)
    async def replay_stop() -> ReplayState:
        """Stop telemetry replay and reset to the beginning."""

        return await source.stop()

    @app.post("/replay/reset", response_model=ReplayState)
    async def replay_reset() -> ReplayState:
        """Reset telemetry replay to the first sample."""

        return await source.reset()

    @app.post("/replay/speed", response_model=ReplayState)
    async def replay_speed(update: SpeedUpdate) -> ReplayState:
        """Update replay speed.

        Args:
            update: Request body containing the new speed multiplier.

        Returns:
            Updated replay state.
        """

        try:
            return await source.set_speed(update.speed)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/replay/stream-interval", response_model=ReplayState)
    async def replay_stream_interval(update: StreamIntervalUpdate) -> ReplayState:
        """Update or clear the fixed stream interval.

        Args:
            update: Request body containing seconds between packets. Use
                ``null`` to restore source timestamp intervals.

        Returns:
            Updated replay state.
        """

        try:
            return await source.set_stream_interval(update.seconds)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/replay/seek", response_model=ReplayState)
    async def replay_seek(request: SeekRequest) -> ReplayState:
        """Seek replay to a sample index.

        Args:
            request: Request body containing the target sample index.

        Returns:
            Updated replay state.
        """

        try:
            return await source.seek(request.index)
        except IndexError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/telemetry/latest", response_model=TelemetryPacket | None)
    async def telemetry_latest() -> TelemetryPacket | None:
        """Return the most recently published telemetry packet."""

        return source.latest_packet

    @app.get("/telemetry/trace", response_model=list[TelemetryTracePoint])
    async def telemetry_trace() -> list[TelemetryTracePoint]:
        """Return all GPS samples needed to preload the full race trace."""
        return source.trace()

    @app.websocket("/ws/telemetry")
    async def telemetry_websocket(websocket: WebSocket) -> None:
        """Stream telemetry packets to a WebSocket client.

        Args:
            websocket: Accepted FastAPI WebSocket connection.

        Returns:
            None.
        """

        await websocket.accept()
        queue = await broadcaster.subscribe()
        logger.info("websocket telemetry client connected")
        try:
            while True:
                packet = await queue.get()
                await websocket.send_json(packet.model_dump())
        except WebSocketDisconnect:
            logger.info("websocket telemetry client disconnected")
        finally:
            await broadcaster.unsubscribe(queue)

    @app.get("/events/telemetry")
    async def telemetry_events() -> EventSourceResponse:
        """Stream telemetry packets as Server-Sent Events.

        Returns:
            EventSourceResponse that yields telemetry events until disconnect.
        """

        async def events():
            """Yield serialized telemetry packets for one SSE client."""

            queue = await broadcaster.subscribe()
            logger.info("sse telemetry client connected")
            try:
                while True:
                    packet = await queue.get()
                    yield {"event": "telemetry", "data": json.dumps(packet.model_dump())}
            finally:
                logger.info("sse telemetry client disconnected")
                await broadcaster.unsubscribe(queue)

        return EventSourceResponse(events())

    _mount_packaged_ui(app)

    return app


def _mount_packaged_ui(app: FastAPI) -> None:
    """Serve the optional static Next.js UI when packaged assets exist."""

    static_dir = Path(__file__).resolve().parents[1] / "ui" / "static"
    if not (static_dir / "index.html").exists():
        logger.debug("packaged telemetry UI not found at %s", static_dir)
        return

    app.mount("/", StaticFiles(directory=static_dir, html=True), name="apexai-ui")
