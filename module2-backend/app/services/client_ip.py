"""
Single source of truth for "which IP is this request from".

Course clarification email: "Take the client IP from the X-Forwarded-For
header when present (first address), falling back to the socket address."
Used everywhere an IP is recorded or keyed on - audit logs, per-IP rate
limit keys, the Singapore-only check-in rule, and the payload sent to
Module 3 - so they all agree on the same address.

Security caveat (see KNOWN-ISSUES.md): X-Forwarded-For is client-supplied
and therefore spoofable. It's honoured unconditionally here because the
course requires it; a production deployment would trust it only when the
socket peer is a known reverse proxy.
"""
import ipaddress
from typing import Optional

from fastapi import Request


def get_client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(first))
        except ValueError:
            pass  # malformed header - fall back to the socket address
    return request.client.host if request.client else None
