"""SSRF guard for outbound requests to user-configured URLs (ntfy).

The ntfy endpoint URL is fully user-controlled and the server POSTs to it, so a
user could point it at an internal/loopback/link-local address and use the server
as a request proxy / port scanner. This validates the scheme and resolves the
host, rejecting any address that is not a normal public unicast address.

httpx does not follow redirects by default, so a validated public host cannot be
redirected to an internal one. DNS rebinding (resolve public now, internal at
connect) is out of scope for this personal app.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """Raised when a URL is not a plain http(s) URL to a public host."""


async def assert_safe_url(url: str) -> None:
    """Raise UnsafeUrlError unless `url` is http(s) and resolves to public IP(s)."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError("URL moet met http:// of https:// beginnen")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("Ongeldige URL")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError("Host kan niet worden opgezocht") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UnsafeUrlError("URL verwijst naar een intern of niet-toegestaan adres")
