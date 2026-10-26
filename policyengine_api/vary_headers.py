"""ASGI middleware that lists each Vary value of a response once."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


def unique_vary_values(vary: str) -> str:
    """Return ``vary`` with each value listed once, in first-seen order.

    Values are compared without regard to case, as HTTP field names are.
    """
    values: list[str] = []
    seen: set[str] = set()
    for value in vary.split(","):
        name = value.strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            values.append(name)
    return ", ".join(values)


class UniqueVaryMiddleware:
    """List each Vary value of every HTTP response once.

    Starlette's CORS and gzip middleware append Origin and Accept-Encoding to
    Vary without checking whether a route already named them. This wraps the
    outermost middleware, so the response that leaves the application names
    each value once.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request through, rewriting a duplicated Vary header."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_unique_vary(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                vary = headers.get("vary")
                if vary is not None:
                    headers["vary"] = unique_vary_values(vary)
            await send(message)

        await self.app(scope, receive, send_with_unique_vary)
