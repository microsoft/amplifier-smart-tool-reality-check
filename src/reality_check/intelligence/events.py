"""What every agent run keeps of its events, so a reader can join at any time and still see them all."""

import asyncio
from collections.abc import AsyncIterator

from reality_check.intelligence.schemas import AgentEvent


class EventLog:
    """An agent run's events in order, replayed to each reader from the start and then live until `terminal`."""

    def __init__(self) -> None:
        self._events: list[AgentEvent] = []
        # Replaced on every append, so a reader waits on the one current when it ran out of events.
        self._appended = asyncio.Event()

    def emit(self, event: AgentEvent) -> None:
        self._events.append(event)
        self._appended.set()
        self._appended = asyncio.Event()

    async def replay(self) -> AsyncIterator[AgentEvent]:
        index = 0
        while True:
            appended = self._appended
            while index < len(self._events):
                event = self._events[index]
                index += 1
                yield event
                if event.kind == "terminal":
                    return
            await appended.wait()


def fresh_input(input_tokens: int | None, *cached: int | None) -> int | None:
    """Input tokens neither read from nor written to a cache, from a count that includes the cached ones."""
    if input_tokens is None:
        return None
    return max(0, input_tokens - sum(tokens or 0 for tokens in cached))
