from __future__ import annotations

import asyncio
from typing import Any


class TrackingPipeline:
    started: asyncio.Event
    release: asyncio.Event
    finished: asyncio.Event
    processed_items: list[Any]

    @classmethod
    def reset(cls) -> None:
        cls.started = asyncio.Event()
        cls.release = asyncio.Event()
        cls.finished = asyncio.Event()
        cls.processed_items = []

    async def process_item(self, item: Any, spider: Any) -> Any:
        type(self).started.set()
        await type(self).release.wait()
        type(self).processed_items.append(item)
        type(self).finished.set()
        return item
