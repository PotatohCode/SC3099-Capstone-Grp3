"""Minimal XSS defense for free-text fields echoed back in API responses."""
import html


def sanitize_text(value: str) -> str:
    """
    Escape HTML special characters so injected markup (e.g. "<script>...")
    can never render as-is if a client dumps the field straight into a page.
    Applied at write-time so every read path stays simple.
    """
    return html.escape(value, quote=True)
