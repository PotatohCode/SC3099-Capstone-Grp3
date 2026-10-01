"""Size guard for base64 images in request bodies (check-in liveness photo,
face enrolment). Without a cap, one huge upload is held in memory, hashed
and forwarded to Module 3 - a cheap way to tie up the service, especially
under the hidden stress tests.

Deliberately not a pydantic max_length: FastAPI's 422 body echoes the
offending input back, which for a multi-MB image would send it straight
back to the client. A 413 with our usual error format is clearer and tiny.
"""
from typing import Optional

from fastapi import status

from app.core.config import get_settings
from app.core.errors import APIError, ErrorCode


def require_image_size(image_b64: Optional[str]) -> None:
    limit = get_settings().MAX_IMAGE_BASE64_CHARS
    if image_b64 is not None and len(image_b64) > limit:
        raise APIError(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Image too large (max {limit} base64 characters)",
            ErrorCode.IMAGE_TOO_LARGE,
        )
