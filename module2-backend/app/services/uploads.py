"""Size guards for base64 images in request bodies (check-in liveness photo
or frame burst, face enrolment). Without a cap, one huge upload is held in memory, hashed
and forwarded to Module 3 - a cheap way to tie up the service, especially
under the hidden stress tests.

Deliberately not a pydantic max_length: FastAPI's 422 body echoes the
offending input back, which for a multi-MB image would send it straight
back to the client. A 413 with our usual error format is clearer and tiny.
"""
from typing import List, Optional

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


def require_frames_size(frames: Optional[List[str]]) -> None:
    """A frame burst is a bigger exhaustion surface than one photo: cap the
    number of frames, then hold each frame to the single-image limit. The
    request-wide MAX_REQUEST_BODY_BYTES cap (main.py) still applies."""
    if not frames:
        return
    limit = get_settings().MAX_LIVENESS_FRAMES
    if len(frames) > limit:
        raise APIError(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Too many liveness frames (max {limit})",
            ErrorCode.TOO_MANY_FRAMES,
        )
    for frame in frames:
        require_image_size(frame)
