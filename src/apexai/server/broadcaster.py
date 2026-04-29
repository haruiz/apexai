"""Async fan-out broadcaster for telemetry stream subscribers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from .schemas import TelemetryPacket

logger = logging.getLogger(__name__)


class Broadcaster:
    """Fan out telemetry packets to independent subscriber queues.

    Each subscriber receives its own bounded queue so a slow client cannot block
    replay or other clients.
    """

    def __init__(self, queue_size: int = 256) -> None:
        """Initialize the broadcaster.

        Args:
            queue_size: Maximum pending packets held per subscriber.

        Returns:
            None.
        """

        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[TelemetryPacket]] = set()
        self._lock = asyncio.Lock()

    async def publish(self, packet: TelemetryPacket) -> None:
        """Publish a telemetry packet to all current subscribers.

        Args:
            packet: Normalized telemetry packet to broadcast.

        Returns:
            None.
        """

        async with self._lock:
            subscribers = list(self._subscribers)

        for queue in subscribers:
            try:
                queue.put_nowait(packet)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(packet)
                except asyncio.QueueFull:
                    logger.debug("dropping telemetry packet for overloaded subscriber")

    async def subscribe(self) -> asyncio.Queue[TelemetryPacket]:
        """Create and register a subscriber queue.

        Returns:
            A bounded asyncio queue that receives future telemetry packets.
        """

        queue: asyncio.Queue[TelemetryPacket] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._subscribers.add(queue)
        logger.info("telemetry client subscribed; subscribers=%s", len(self._subscribers))
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[TelemetryPacket]) -> None:
        """Remove a subscriber queue.

        Args:
            queue: Queue previously returned by :meth:`subscribe`.

        Returns:
            None.
        """

        async with self._lock:
            self._subscribers.discard(queue)
            count = len(self._subscribers)
        logger.info("telemetry client unsubscribed; subscribers=%s", count)

    async def stream(self) -> AsyncIterator[TelemetryPacket]:
        """Yield telemetry packets from a temporary subscription.

        Returns:
            Async iterator of normalized telemetry packets.
        """

        queue = await self.subscribe()
        try:
            while True:
                yield await queue.get()
        finally:
            await self.unsubscribe(queue)
