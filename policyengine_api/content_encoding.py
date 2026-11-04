"""Gzip negotiation that weighs Accept-Encoding qualities.

Starlette's ``GZipMiddleware`` compresses whenever the text "gzip" appears in
Accept-Encoding, so ``gzip;q=0`` (an explicit refusal) still gets gzip. The
application and the routes that send stored gzip bytes decide with
``accepts_gzip`` instead, so a response's encoding is the one the client
accepts and every route agrees with the middleware.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware, GZipResponder, IdentityResponder

if TYPE_CHECKING:
    from starlette.types import Receive, Scope, Send

_GZIP_CODINGS: Final = frozenset({"gzip", "x-gzip"})


def _quality(parameters: str) -> float:
    for parameter in parameters.split(";"):
        name, _, value = parameter.strip().partition("=")
        if name.strip().lower() == "q":
            try:
                return float(value)
            except ValueError:
                return 0.0
    return 1.0


def accepts_gzip(accept_encoding: str | None) -> bool:
    """Return whether an Accept-Encoding value accepts gzip.

    An explicit gzip entry decides; otherwise ``*`` does. A quality of 0
    refuses the coding, and a coding name must match exactly.
    """
    wildcard_quality: float | None = None
    for entry in (accept_encoding or "").split(","):
        coding, _, parameters = entry.partition(";")
        name = coding.strip().lower()
        if name in _GZIP_CODINGS:
            return _quality(parameters) > 0
        if name == "*":
            wildcard_quality = _quality(parameters)
    return wildcard_quality is not None and wildcard_quality > 0


class NegotiatedGZipMiddleware(GZipMiddleware):
    """``GZipMiddleware`` that compresses only for clients that accept gzip.

    Responses that already name a Content-Encoding pass through unchanged, as
    in the parent class.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Choose the gzip or identity responder by ``accepts_gzip``."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        accept_encoding = Headers(scope=scope).get("accept-encoding")
        if accepts_gzip(accept_encoding):
            responder = GZipResponder(
                self.app, self.minimum_size, compresslevel=self.compresslevel
            )
            await responder(scope, receive, send)
            return
        await IdentityResponder(self.app, self.minimum_size)(scope, receive, send)
