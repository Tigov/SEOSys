"""Single place that creates outbound HTTP clients.

Tests replace `transport_factory` so the crawler and site adapter talk to the
demo site in-process instead of over the network.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Callable
from urllib.parse import urlparse

import httpx

from .config import settings

transport_factory: Callable[[], httpx.AsyncBaseTransport | None] = lambda: None


def make_client(timeout: float = 15.0) -> httpx.AsyncClient:
    transport = transport_factory()
    kwargs: dict = {"timeout": timeout, "headers": {"User-Agent": settings.crawl_user_agent}, "follow_redirects": False}
    if transport is not None:
        kwargs["transport"] = transport
    return httpx.AsyncClient(**kwargs)


class BlockedHostError(ValueError):
    pass


def assert_public_host(url: str) -> None:
    """SSRF guard: refuse private, loopback and link-local targets unless explicitly allowed (local dev).

    Checked before every request. Production must also pin the resolved IP in a custom transport,
    because httpx resolves the name again and DNS rebinding could swap the address in between.
    """
    if settings.allow_private_hosts:
        return
    host = urlparse(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise BlockedHostError(f"Cannot find the website {host}. Check the address.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise BlockedHostError(f"{host} points to a private network address, which is not allowed.")
