"""
SAIV Face Recognition & Risk Service - Module 3

This is the skeleton implementation for the Face Recognition module.
Students must implement face enrollment, verification, liveness detection,
and risk scoring.

Privacy Requirements:
- NO raw face images should be stored
- Process images in-memory only
- Store only SHA-256 hashes of face embeddings

Recommended Libraries:
- MediaPipe: Face detection and 468-landmark face mesh
- OpenCV: Image processing
- Pillow: Image loading from base64
- NumPy: Numerical operations
"""

import base64
import functools
import os
import re
import threading
import time
from io import BytesIO

import face_recognition
import mediapipe as mp
import numpy as np
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional, Dict, List, Any

app = FastAPI(
    title="SAIV Face Recognition Service",
    description="Face enrollment, verification, liveness detection, and risk scoring service",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# METRICS (GET /metrics, scraped by module4-observability/prometheus.yml)
# =============================================================================
#
# Names start with face_ instead of reusing the backend's
# http_request_duration_seconds: Module 4's system-health dashboard sums that
# name across every scrape job, so face-service latency (seconds, under load)
# would be mixed into the backend's API latency and error-rate panels.
#
# Each uvicorn worker process keeps its own counters, and a scrape reaches only
# one worker. When PROMETHEUS_MULTIPROC_DIR is set (the Dockerfile sets it),
# prometheus_client writes every worker's values into that folder and /metrics
# reports their sum. Without it (e.g. a local single-process run), the normal
# in-process registry is used.

face_request_duration_seconds = Histogram(
    "face_request_duration_seconds",
    "Face service request latency in seconds",
    ["method", "path", "status_code"],
    # 5 s and 15 s are the backend's timeouts (single image / frame burst).
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 15, 30, 60),
)
face_enroll_total = Counter("face_enroll_total", "Face enrollments by outcome", ["outcome"])
face_verify_total = Counter("face_verify_total", "Face verifications by outcome", ["outcome"])
face_liveness_total = Counter("face_liveness_total", "Liveness checks by outcome", ["outcome"])


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Records face_request_duration_seconds for every request. The path label
    is the route template (e.g. "/face/verify"), not the raw URL, and
    requests that match no route are labelled "unmatched", so random URLs
    can't create unbounded label values.
    """

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        face_request_duration_seconds.labels(
            method=request.method,
            path=getattr(route, "path", None) or "unmatched",
            status_code=str(response.status_code),
        ).observe(time.perf_counter() - start)
        return response


app.add_middleware(MetricsMiddleware)


def _count_outcome(counter, outcome_of):
    """
    Decorator for a sync endpoint: once it returns, increment `counter`
    with outcome=outcome_of(response). This keeps counting out of the
    endpoints' many early returns. functools.wraps preserves the endpoint's
    signature and docstring, which FastAPI reads for request parsing and
    /docs.
    """
    def decorator(endpoint):
        @functools.wraps(endpoint)
        def wrapper(*args, **kwargs):
            response = endpoint(*args, **kwargs)
            counter.labels(outcome=outcome_of(response)).inc()
            return response
        return wrapper
    return decorator


def _enroll_outcome(response):
    return "success" if response.enrollment_successful else "failed"


def _verify_outcome(response):
    return {True: "match", False: "no_match"}.get(response.match_passed, "not_compared")


def _liveness_outcome(response):
    return {True: "passed", False: "failed"}.get(response.liveness_passed, "not_assessed")


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class FaceEnrollRequest(BaseModel):
    """Request model for face enrollment."""
    user_id: str
    image: str  # Base64 encoded image
    camera_consent: bool = False


class FaceEnrollResponse(BaseModel):
    """Response model for face enrollment."""
    enrollment_successful: bool
    face_template_hash: str  # 64-char SHA-256 hex string
    quality_score: float  # 0.0 to 1.0
    details: Dict[str, Any]


class FaceVerifyRequest(BaseModel):
    """Request model for face verification."""
    image: str  # Base64 encoded image
    reference_template_hash: str  # Hash from enrollment


class FaceVerifyResponse(BaseModel):
    """Response model for face verification."""
    # None when no comparison happened (undecodable image, no face, invalid
    # reference hash): module2 hard-rejects on False for face-required sessions.
    match_passed: Optional[bool]
    match_score: float  # 0.0 to 1.0
    match_threshold: float  # Default: 0.70
    face_detected: bool
    current_template_hash: str


class LivenessRequest(BaseModel):
    """
    Request model for liveness check. Two shapes, per
    module2-backend/api-docs/API-FOR-FACE-RECOGNITION.md §3:
    (a) single image: challenge_response only (the course's public tests);
    (b) frame burst: `frames` (1-30, oldest first, raw/not mirrored), plus
        `challenge_sequence` when the backend issued a challenge.
    """
    challenge_response: str  # Base64 encoded image (in shape (b): the middle frame or a separate photo)
    # "passive", "sequence" (backend-issued challenge) or any client label;
    # free text on purpose - the backend forwards labels it doesn't validate.
    challenge_type: str = "blink"
    frames: Optional[List[str]] = None
    challenge_sequence: Optional[List[str]] = None  # e.g. ["blink", "turn_left"]


class LivenessResponse(BaseModel):
    """Response model for liveness check."""
    # Optional[bool], not bool: module2-backend/api-docs/API-FOR-FACE-
    # RECOGNITION.md wants None (not False) for "couldn't assess" cases
    # (no face detected, undecodable image) - an explicit False triggers a
    # hard-reject override on their end regardless of score, and is meant
    # to be reserved for cases where liveness was actually determined to
    # have failed. See check_liveness for where None vs False is decided.
    liveness_passed: Optional[bool]
    liveness_score: float  # 0.0 to 1.0
    liveness_threshold: float  # Default: 0.60
    face_embedding_hash: str
    details: Dict[str, Any]
    # Frame bursts with a challenge_sequence only (None otherwise):
    # were all steps performed, in order? None = couldn't tell (the backend
    # treats it as unverified). False lets the student retry, so only send it
    # when the steps clearly weren't done.
    challenge_passed: Optional[bool] = None
    # One entry per step in sequence order; the backend tells the student to
    # redo the first False one.
    steps_passed: Optional[List[bool]] = None


class GeolocationData(BaseModel):
    """Geolocation data for risk assessment."""
    latitude: float
    longitude: float
    accuracy: float


class RiskAssessRequest(BaseModel):
    """Request model for risk assessment."""
    liveness_score: Optional[float] = None
    face_match_score: Optional[float] = None
    device_signature: Optional[str] = None
    device_public_key: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    geolocation: Optional[GeolocationData] = None


class RiskAssessResponse(BaseModel):
    """Response model for risk assessment."""
    risk_score: float  # 0.0 to 1.0
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    pass_threshold: bool
    risk_threshold: float  # Default: 0.50
    signal_breakdown: Dict[str, float]
    recommendations: List[str]


# =============================================================================
# HEALTH & ROOT ENDPOINTS
# =============================================================================

@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "service": "SAIV Face Recognition & Risk Service"}


@app.get("/metrics")
async def metrics():
    """
    Prometheus metrics (see the METRICS section above). A plain route, as in
    module2-backend, rather than mounting prometheus_client's ASGI app:
    Starlette's Mount redirects /metrics to /metrics/, which a scraper may not
    follow. Sums all worker processes when PROMETHEUS_MULTIPROC_DIR is set.
    """
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def root():
    """
    List available endpoints.

    Bare paths (not "METHOD /path - description" strings) - tests/public/
    test_face_recognition.py checks `"/face/enroll" in endpoints` via
    exact list membership, which a longer descriptive string never
    satisfies. This is a real discrepancy between the test and
    docs/API-SPECIFICATION.md's own root-endpoint example (which uses the
    descriptive format) - the runnable test wins here.
    """
    return {
        "service": "SAIV Face Recognition & Risk Service",
        "version": "1.0.0",
        "endpoints": [
            "/health",
            "/face/enroll",
            "/face/verify",
            "/face/match",
            "/liveness/check",
            "/risk/assess",
            "/metrics",
        ]
    }


# =============================================================================
# FACE ENROLLMENT ENDPOINT (REQUIRED - 4 points in public tests)
# =============================================================================

# quality_score heuristics (not spec'd anywhere - see enroll_face docstring)
_QUALITY_RESOLUTION_BASELINE_PX = 640 * 480  # "good enough" webcam resolution
_QUALITY_FACE_AREA_RATIO_TARGET = 0.15  # face covering ~15% of frame -> full marks


@app.post("/face/enroll", response_model=FaceEnrollResponse, status_code=201)
@_count_outcome(face_enroll_total, _enroll_outcome)
def enroll_face(request: FaceEnrollRequest):
    """
    Enroll a user's face for future verification.

    TODO: Implement the following:
    1. Validate camera_consent is True (return 400 if False)
    2. Decode base64 image to numpy array
    3. Detect face using MediaPipe FaceDetection
    4. If no face detected, return 400 with "No face detected"
    5. Extract face features/embedding
    6. Generate SHA-256 hash of embedding (64 hex chars)
    7. Calculate quality score based on:
       - Face detection confidence
       - Image resolution
       - Face size relative to image
    8. Return enrollment response

    Success Criteria:
    - Face detected with confidence >= 0.7
    - Quality score >= 0.5
    - Returns 64-char SHA-256 hex hash

    ---
    Implemented per the steps above, using the SimHash-based
    generate_face_hash (see that function's docstring for why it's not
    literally SHA-256), with one deviation from step 1/4's literal "return
    400": per module2-backend/api-docs/API-FOR-FACE-RECOGNITION.md, module2
    treats any non-2xx response from us as a service failure (trips their
    circuit breaker, returns 503 to their own caller) rather than reading
    it as "no face detected" - they only read enrollment_successful from a
    normal 2xx body to decide that. So failure cases below return a 201
    with enrollment_successful=False instead of raising HTTPException,
    which is what lets module2 actually surface their own 400
    NO_FACE_DETECTED to their caller as documented. face_template_hash and
    quality_score are required fields on the response model even when
    there's nothing real to put there, hence the placeholders.

    "No face detected" here covers three distinct failure reasons (no
    consent, decode failure, no usable face) - the reason is only for our
    own logging via `details`, since module2 says they just need the
    boolean.

    quality_score (on success) averages three 0-1 components: detection
    confidence, image resolution (relative to a 640x480 baseline), and
    face size relative to the full image (relative to the face covering
    ~15% of the frame). This isn't a spec'd formula, just a reasonable
    combination of the three signals the docstring calls out.
    """
    if not request.camera_consent:
        return FaceEnrollResponse(
            enrollment_successful=False,
            face_template_hash="",
            quality_score=0.0,
            details={"face_detected": False, "reason": "camera_consent_required"},
        )

    try:
        image_array = decode_base64_image(request.image)
    except ValueError as exc:
        return FaceEnrollResponse(
            enrollment_successful=False,
            face_template_hash="",
            quality_score=0.0,
            details={"face_detected": False, "reason": f"invalid_image: {exc}"},
        )

    detection = detect_face(image_array)
    if detection is None:
        return FaceEnrollResponse(
            enrollment_successful=False,
            face_template_hash="",
            quality_score=0.0,
            details={"face_detected": False, "reason": "no_face_detected"},
        )

    embedding = extract_face_embedding(image_array, detection)
    if embedding is None:
        return FaceEnrollResponse(
            enrollment_successful=False,
            face_template_hash="",
            quality_score=0.0,
            details={"face_detected": False, "reason": "no_face_detected"},
        )

    face_hash = generate_face_hash(embedding)

    confidence = float(detection.score[0])
    height, width = image_array.shape[:2]
    resolution_score = min(1.0, (width * height) / _QUALITY_RESOLUTION_BASELINE_PX)
    bbox = detection.location_data.relative_bounding_box
    face_size_score = min(1.0, (bbox.width * bbox.height) / _QUALITY_FACE_AREA_RATIO_TARGET)
    quality_score = (confidence + resolution_score + face_size_score) / 3

    if quality_score >= 0.7:
        image_quality = "good"
    elif quality_score >= 0.5:
        image_quality = "fair"
    else:
        image_quality = "poor"

    return FaceEnrollResponse(
        enrollment_successful=True,
        face_template_hash=face_hash,
        quality_score=round(quality_score, 4),
        details={
            "face_detected": True,
            "face_detection_confidence": round(confidence, 4),
            "image_quality": image_quality,
        },
    )


# =============================================================================
# FACE VERIFICATION ENDPOINT (REQUIRED - 4 points in public tests)
# =============================================================================

@app.post("/face/verify", response_model=FaceVerifyResponse)
@_count_outcome(face_verify_total, _verify_outcome)
def verify_face(request: FaceVerifyRequest):
    """
    Verify a face against an enrolled template.

    TODO: Implement the following:
    1. Decode base64 image to numpy array
    2. Detect face using MediaPipe FaceDetection
    3. If no face detected, return with face_detected=False
    4. Extract face features/embedding
    5. Generate SHA-256 hash of current face
    6. Compare hashes or embeddings (choose your approach)
    7. Calculate match_score (0.0 to 1.0)
    8. match_passed = (match_score >= 0.70)

    Note: Hash comparison alone gives binary match. For continuous
    scores, consider perceptual hashing or embedding similarity.

    ---
    Implemented per the steps above. Unlike /face/enroll, step 3 here
    already says "return with face_detected=False" rather than raising -
    no doc conflict to resolve, this one already matches module2's
    graceful-degrade contract (API-FOR-FACE-RECOGNITION.md: on failure
    they set face_match_passed/score to None without failing the
    check-in). decode failures, no detection, and no usable embedding are
    all treated the same way: face_detected=False, match_passed=None,
    match_score=0.0, current_template_hash="". None, not False:
    API-FOR-FACE-RECOGNITION.md reserves False for "compared two faces and
    they differ" - module2 reads only match_passed and hard-rejects on False
    for face-required sessions, so a blurry photo must not look like a
    different person. tests/public's no-face test accepts face_detected=False.

    match_passed is decided directly against dlib's own documented
    threshold (_DLIB_EUCLIDEAN_MATCH_THRESHOLD = 0.6 euclidean distance),
    not by comparing match_score to 0.70 - deliberately simple for now.
    The euclidean distance itself is reconstructed from the Hamming
    distance between the two SimHash values (see _hamming_distance),
    since only the hashes are available here, never the raw reference
    embedding - SimHash preserves angle/cosine similarity, and cosine
    similarity converts to euclidean distance via
    ||a-b||^2 = ||a||^2+||b||^2-2*a.b, using _ASSUMED_EMBEDDING_NORM for
    both vectors since actual magnitude can't be recovered from the hash.
    Verified empirically against obama/obama2/obama3/biden before relying
    on it (see diagnose_dlib.py).

    match_score is kept simple and just self-consistent with that same
    0.6/0.70 boundary (match_score = 1 - euclidean/2, so euclidean==0.6
    lands exactly on match_score==0.70) - it's reported for the response
    schema and the "match_score >= 0.7 on a real match" test, but doesn't
    itself drive match_passed. This can be revisited/made more precise
    later if needed.

    A reference_template_hash that isn't a valid 64-char hex SimHash
    (e.g. empty string, from a user who never successfully enrolled, or
    not valid hex) can't be compared - _hamming_distance raises
    ValueError, treated as "couldn't compare" (match_passed=None,
    match_score=0.0) rather than a crash, since it's an expected data
    state, not a service failure.
    """
    try:
        image_array = decode_base64_image(request.image)
    except ValueError:
        return FaceVerifyResponse(
            match_passed=None,
            match_score=0.0,
            match_threshold=0.70,
            face_detected=False,
            current_template_hash="",
        )

    detection = detect_face(image_array)
    if detection is None:
        return FaceVerifyResponse(
            match_passed=None,
            match_score=0.0,
            match_threshold=0.70,
            face_detected=False,
            current_template_hash="",
        )

    embedding = extract_face_embedding(image_array, detection)
    if embedding is None:
        return FaceVerifyResponse(
            match_passed=None,
            match_score=0.0,
            match_threshold=0.70,
            face_detected=False,
            current_template_hash="",
        )

    current_hash = generate_face_hash(embedding)

    try:
        distance = _hamming_distance(current_hash, request.reference_template_hash)
        fraction = distance / _SIMHASH_BITS
        estimated_cos_sim = np.cos(fraction * np.pi)
        estimated_euclidean = np.sqrt(2 * (_ASSUMED_EMBEDDING_NORM ** 2) * (1 - estimated_cos_sim))
        match_passed = bool(estimated_euclidean <= _DLIB_EUCLIDEAN_MATCH_THRESHOLD)
        match_score = max(0.0, 1 - estimated_euclidean / 2.0)
    except ValueError:
        match_passed = None
        match_score = 0.0

    return FaceVerifyResponse(
        match_passed=match_passed,
        match_score=round(match_score, 4),
        match_threshold=0.70,
        face_detected=True,
        current_template_hash=current_hash,
    )


@app.post("/face/match")
def match_face(request: FaceVerifyRequest):
    """
    Legacy face matching endpoint. Redirects to /face/verify.
    Kept for backwards compatibility.
    """
    return verify_face(request)


# =============================================================================
# LIVENESS DETECTION ENDPOINT (REQUIRED - partial; BONUS for advanced)
# =============================================================================

@app.post("/liveness/check", response_model=LivenessResponse)
@_count_outcome(face_liveness_total, _liveness_outcome)
def check_liveness(request: LivenessRequest):
    """
    Perform liveness detection on submitted image.

    TODO: Implement the following:
    1. Decode base64 image to numpy array
    2. Detect face using MediaPipe FaceDetection
    3. If no face detected, return with liveness_passed=False
    4. Analyze face for liveness signals:

    REQUIRED (for partial credit):
    - Basic face detection confidence
    - Image quality assessment
    - Face size validation

    BONUS (for extra credit - see API-SPECIFICATION.md):
    - MediaPipe Face Mesh 3D analysis (468 landmarks)
    - Depth cue analysis (nose_tip_z coordinate)
    - Face mesh completeness check
    - Challenge-response detection (blink, head movement)

    Challenge Types:
    - "passive": No user action required (depth/texture analysis)
    - "blink": Detect eye blink (compare eye aspect ratios)
    - "head_turn": Detect head rotation (face mesh landmarks)

    5. Calculate liveness_score (0.0 to 1.0)
    6. liveness_passed = (liveness_score >= 0.60)
    7. Generate face embedding hash

    Depth Analysis Hints (BONUS):
    - Use MediaPipe FaceMesh to get 3D landmarks
    - Real faces: |nose_tip_z| > 0.03 (significant depth)
    - Flat images: |nose_tip_z| < 0.01 (minimal depth)

    ---
    Implemented: REQUIRED signals (detection confidence, image
    resolution/face-size "quality" - reusing enroll_face's
    _QUALITY_RESOLUTION_BASELINE_PX/_QUALITY_FACE_AREA_RATIO_TARGET
    constants) plus the BONUS depth + mesh-completeness signals from
    analyze_face_mesh, averaged equally (25% each). Texture analysis and
    color-distribution analysis (the other two BONUS signals
    docs/API-SPECIFICATION.md lists) are NOT implemented - those need
    print/screen artifact and skin-tone-variance detection, a
    meaningfully larger scope than what's built here. This isn't a
    spec'd weighting scheme either way (API-SPECIFICATION.md's 30/25/25/20
    split only covers the 3D-cue portion, not how to blend it with the
    REQUIRED-tier signals), so treat the equal 25% split as a reasonable
    default open to adjustment.

    Request shape (a), a single image, is scored this way whatever its
    challenge_type: one image can't show a blink or a head turn. Shape (b),
    a frame burst (`frames` present), goes to _check_liveness_burst
    instead; see there.

    "No face detected" and image-decode failure both return with no
    HTTPException raised (this docstring's own step 3 already says
    "return with", matching module2's graceful-degrade pattern) - but
    liveness_passed=None, not False, for both. Corrected from an earlier
    version that used False here: module2-backend/api-docs/API-FOR-FACE-
    RECOGNITION.md is explicit that False is reserved for an actually
    *determined* liveness failure (e.g. depth analysis positively
    indicating a flat/printed photo), and triggers a hard-reject override
    on their end regardless of score - "couldn't even find a face to
    assess" is an unattempted check, not a determination, and forcing it
    to False would trigger that override incorrectly (e.g. for a merely
    blurry or badly-angled photo, not necessarily a spoofing attempt).
    There's nothing to hash either way, so face_embedding_hash is "".
    """
    if request.frames:
        return _check_liveness_burst(request)

    try:
        image_array = decode_base64_image(request.challenge_response)
    except ValueError:
        return LivenessResponse(
            liveness_passed=None,
            liveness_score=0.0,
            liveness_threshold=0.60,
            face_embedding_hash="",
            details={"face_detected": False, "reason": "invalid_image"},
        )
    return _passive_liveness(image_array)


def _passive_liveness(image_array) -> LivenessResponse:
    """
    Single-image liveness on a decoded image: the scoring described in
    check_liveness's docstring. Used for request shape (a), and in a frame
    burst on its most front-facing frame.
    """
    detection = detect_face(image_array)
    if detection is None:
        return LivenessResponse(
            liveness_passed=None,
            liveness_score=0.0,
            liveness_threshold=0.60,
            face_embedding_hash="",
            details={"face_detected": False, "reason": "no_face_detected"},
        )

    embedding = extract_face_embedding(image_array, detection)
    face_hash = generate_face_hash(embedding) if embedding is not None else ""

    confidence = float(detection.score[0])
    height, width = image_array.shape[:2]
    resolution_score = min(1.0, (width * height) / _QUALITY_RESOLUTION_BASELINE_PX)
    bbox = detection.location_data.relative_bounding_box
    face_size_score = min(1.0, (bbox.width * bbox.height) / _QUALITY_FACE_AREA_RATIO_TARGET)
    quality_signal = (resolution_score + face_size_score) / 2

    mesh_result = analyze_face_mesh(image_array)
    depth_signal = min(1.0, abs(mesh_result["nose_tip_z"]) / 0.03)
    mesh_signal = 1.0 if mesh_result["face_mesh_complete"] else 0.0

    liveness_score = (confidence + quality_signal + depth_signal + mesh_signal) / 4

    return LivenessResponse(
        liveness_passed=liveness_score >= 0.60,
        liveness_score=round(liveness_score, 4),
        liveness_threshold=0.60,
        face_embedding_hash=face_hash,
        details={
            "face_detected": True,
            "face_detection_confidence": round(confidence, 4),
            "face_mesh_complete": mesh_result["face_mesh_complete"],
            "landmark_count": mesh_result["landmark_count"],
            "nose_tip_z": mesh_result["nose_tip_z"],
            "depth_quality": mesh_result["depth_quality"],
        },
    )


def _check_liveness_burst(request: LivenessRequest) -> LivenessResponse:
    """
    Request shape (b): a burst of frames, per
    module2-backend/api-docs/API-FOR-FACE-RECOGNITION.md §3.

    - Frames that won't decode are skipped rather than failing the request:
      a 4xx would only make the backend treat this attempt as unverified.
    - Each frame gets its head yaw (_frame_features). The passive check runs
      on the most front-facing frame, not on challenge_response: that field
      is the burst's middle frame (which can catch the head mid-turn) or,
      if the client also sent one, a separate photo.
    - liveness_passed: true when the passive score passes, otherwise None,
      never False. The backend treats False as a spoof (check-in rejected,
      no more attempts), and a low passive score on a webcam frame isn't
      evidence of one.
    - challenge_passed / steps_passed: from evaluate_challenge when the
      backend sent a challenge_sequence; None otherwise (a burst without a
      challenge has nothing to check the movements against).
    """
    decoded = []  # (index in request.frames, image)
    for index, frame in enumerate(request.frames):
        try:
            decoded.append((index, decode_base64_image(frame)))
        except ValueError:
            continue
    features = [(index, image, _frame_features(image)) for index, image in decoded]
    with_face = [(index, image, f) for index, image, f in features if f is not None]
    burst_details = {
        "frames_received": len(request.frames),
        "frames_decoded": len(decoded),
        "frames_with_face": len(with_face),
    }

    challenge_passed, steps_passed = None, None
    if request.challenge_sequence:
        challenge_passed, steps_passed = evaluate_challenge([f for _, _, f in features], request.challenge_sequence)
        burst_details["challenge"] = "insufficient_frames" if steps_passed is None else "evaluated"
    else:
        burst_details["challenge"] = "no_sequence"

    if not with_face:
        return LivenessResponse(
            liveness_passed=None,
            liveness_score=0.0,
            liveness_threshold=0.60,
            face_embedding_hash="",
            details={"face_detected": False, "reason": "no_face_in_frames", **burst_details},
        )

    frontal_index, frontal_image, _ = min(with_face, key=lambda item: abs(item[2]["yaw"]))
    response = _passive_liveness(frontal_image)
    if response.liveness_passed is False:
        response.liveness_passed = None
    response.challenge_passed = challenge_passed
    response.steps_passed = steps_passed
    response.details.update(burst_details, frontal_frame_index=frontal_index)
    return response


# =============================================================================
# RISK ASSESSMENT ENDPOINT (REQUIRED - 3 points in public tests)
# =============================================================================

_RISK_WEIGHTS = {
    "liveness": 0.25,
    "face_match": 0.25,
    "device": 0.20,
    "network": 0.15,
    "geolocation": 0.15,
}


@app.post("/risk/assess", response_model=RiskAssessResponse)
async def assess_risk(request: RiskAssessRequest):
    """
    Perform multi-signal risk assessment.

    TODO: Implement the following:
    1. Collect all available signals from request
    2. Calculate individual signal scores (0.0 = safe, 1.0 = risky)
    3. Apply weighted fusion:
       - Liveness: 25%
       - Face match: 25%
       - Device attestation: 20%
       - Network/VPN: 15%
       - Geolocation: 15%
    4. Calculate combined risk_score
    5. Determine risk_level:
       - LOW: risk_score < 0.3
       - MEDIUM: 0.3 <= risk_score < 0.5
       - HIGH: 0.5 <= risk_score < 0.7
       - CRITICAL: risk_score >= 0.7
    6. pass_threshold = (risk_score < 0.50)
    7. Generate recommendations for low-scoring signals

    Signal Analysis:
    - Liveness: Invert score (low liveness = high risk)
    - Face match: Invert score (low match = high risk)
    - Device: Check signature validity, public key format
    - Network: Detect VPN/proxy (private IPs, Tor exit nodes)
    - Geolocation: Check accuracy, validate coordinates

    VPN/Proxy Detection Hints:
    - Private IP ranges: 10.x.x.x, 172.16-31.x.x, 192.168.x.x
    - Check user_agent for VPN indicators
    - High geolocation accuracy (< 10m) might be spoofed
    - Very low accuracy (> 5000m) indicates issues

    ---
    Implemented per the steps above. Every RiskAssessRequest field is
    Optional, so each signal is scored 0.0 (no risk contribution) when
    the underlying data simply wasn't provided - this isn't spec'd
    explicitly, but treating "not assessed" as risk-free (rather than
    penalizing missing-but-not-required data, or treating it as fully
    risky) seemed the least surprising default; flag if you want a
    different convention. Weights (_RISK_WEIGHTS) and the LOW/MEDIUM/
    HIGH/CRITICAL thresholds are exactly as spec'd above (and agree with
    docs/API-SPECIFICATION.md's Risk Level Mapping - no conflict there,
    unlike the older Module3-FaceRecognition-Design.pdf slide which uses
    different 0.3/0.6/0.8 cutoffs for a similar but not identical scale).

    Device signal: there's no real cryptographic signature verification
    here (that's what the separate, explicitly "OPTIONAL - Not Tested"
    /device/attest endpoint would do) - this only checks that
    device_public_key looks like a PEM block and that both
    device_signature and device_public_key are present together. That's
    a shallow heuristic, not real attestation.

    Geolocation signal: flags accuracy outside the hinted 10m-5000m
    "normal" band, or lat/lng outside valid ranges, as risky. The
    specific risk values chosen for "in range" vs "out of range" vs
    "invalid coordinates" (0.1 / 0.6 / 1.0) aren't spec'd, just ordered
    sensibly.

    signal_breakdown holds each signal's *weighted* contribution
    (weight * component risk), matching docs/API-SPECIFICATION.md's
    example response where the breakdown values sum to risk_score. That
    weight is renormalized across only the signals actually present in
    the request (present_risks below), not the full fixed weights -
    otherwise an absent signal (scored 0 risk, since there's no evidence
    either way) still eats its full weight in the denominator, diluting
    risk_score even when every signal that IS present is clearly bad. A
    concrete case this fixes: liveness=0.2, face_match=0.3, a private IP,
    and a "vpn-client" user agent, with no device/geolocation data at
    all - under fixed weights this computes to 0.495 (just under the 0.5
    threshold, purely because device's and geolocation's unused 35%
    combined weight still counted toward the total); renormalized across
    just the three signals actually present, it correctly comes out above
    0.5.

    Recommendations reuse the exact strings from
    docs/API-SPECIFICATION.md's "Recommendations Logic" section, since
    that's the only place specific wording is given.

    `async def`, unlike the image endpoints: it's pure arithmetic with no
    blocking calls, so it runs directly on the event loop. As a sync
    handler it needed a thread-pool thread, and under load every thread
    was taken by image requests queued on _model_lock, so this took
    seconds instead of milliseconds.
    """
    def _signal_risk(score: Optional[float]) -> float:
        return 1 - max(0.0, min(1.0, score)) if score is not None else 0.0

    present_risks = {}

    if request.liveness_score is not None:
        present_risks["liveness"] = _signal_risk(request.liveness_score)
    if request.face_match_score is not None:
        present_risks["face_match"] = _signal_risk(request.face_match_score)

    if request.device_signature and request.device_public_key:
        is_pem = request.device_public_key.strip().startswith("-----BEGIN")
        present_risks["device"] = 0.1 if is_pem else 0.7
    elif request.device_signature or request.device_public_key:
        present_risks["device"] = 0.6  # one present without the other - incomplete attestation

    if request.ip_address or request.user_agent:
        is_vpn, vpn_confidence = detect_vpn_proxy(request.ip_address, request.user_agent)
        present_risks["network"] = vpn_confidence if is_vpn else 0.0

    geo = request.geolocation
    if geo is not None:
        if not (-90 <= geo.latitude <= 90 and -180 <= geo.longitude <= 180):
            present_risks["geolocation"] = 1.0
        elif geo.accuracy < 10 or geo.accuracy > 5000:
            present_risks["geolocation"] = 0.6
        else:
            present_risks["geolocation"] = 0.1

    total_present_weight = sum(_RISK_WEIGHTS[name] for name in present_risks)
    signal_breakdown = {}
    for name in _RISK_WEIGHTS:
        if name in present_risks and total_present_weight > 0:
            normalized_weight = _RISK_WEIGHTS[name] / total_present_weight
            signal_breakdown[name] = round(normalized_weight * present_risks[name], 4)
        else:
            signal_breakdown[name] = 0.0
    risk_score = round(sum(signal_breakdown.values()), 4)

    liveness_risk = present_risks.get("liveness", 0.0)
    face_match_risk = present_risks.get("face_match", 0.0)
    network_risk = present_risks.get("network", 0.0)
    geolocation_risk = present_risks.get("geolocation", 0.0)

    if risk_score < 0.3:
        risk_level = "LOW"
    elif risk_score < 0.5:
        risk_level = "MEDIUM"
    elif risk_score < 0.7:
        risk_level = "HIGH"
    else:
        risk_level = "CRITICAL"

    recommendations = []
    if liveness_risk > 0.5:
        recommendations.append("Improve lighting and face visibility")
    if face_match_risk > 0.5:
        recommendations.append("Re-enroll face or improve image quality")
    if network_risk > 0.5:
        recommendations.append("Disable VPN for check-in")
    if geolocation_risk > 0.5:
        recommendations.append("Enable precise location services")

    return RiskAssessResponse(
        risk_score=round(risk_score, 4),
        risk_level=risk_level,
        pass_threshold=risk_score < 0.50,
        risk_threshold=0.50,
        signal_breakdown=signal_breakdown,
        recommendations=recommendations,
    )


# =============================================================================
# HELPER FUNCTIONS (Implement these to support your endpoints)
# =============================================================================

def decode_base64_image(base64_string: str) -> np.ndarray:
    """
    Decode a base64 encoded image to a numpy array.

    TODO: Implement using:
    - base64.b64decode()
    - PIL.Image.open(BytesIO(...))
    - numpy.array()

    Handle errors gracefully (invalid base64, corrupt image, etc.)

    ---
    Implemented: raises ValueError if the string isn't valid base64, or
    doesn't decode to a readable image. Callers (the endpoint handlers)
    are responsible for turning that into the appropriate HTTP error.

    Whitespace (spaces, line breaks) is removed before decoding: base64
    wrapped across lines is still valid data, but validate=True rejects it,
    which made /face/verify report "couldn't compare" for a good photo.
    """
    base64_string = "".join((base64_string or "").split())
    if not base64_string:
        raise ValueError("Image data is empty")

    try:
        image_bytes = base64.b64decode(base64_string, validate=True)
        image = Image.open(BytesIO(image_bytes))
        image = image.convert("RGB")
    except Exception as exc:
        raise ValueError(f"Could not decode image: {exc}") from exc

    return np.array(image)


# --- Shared face models (one set per process) ---
#
# The route handlers are plain `def`, so FastAPI runs them on a thread pool
# (~40 threads) and quick endpoints like /risk/assess no longer wait behind
# image work. The face models themselves, though, are used by one request at
# a time per process, under _model_lock:
# - dlib (via face_recognition) is ~95% of each request's time and its models
#   are module-level objects that aren't safe to call from several threads at
#   once, so it was going to be one-at-a-time anyway.
# - MediaPipe solution objects aren't thread-safe either. An earlier version
#   gave each thread its own copy instead; under load that built dozens of
#   models at once after a restart (100 parallel requests hung for 120s) and
#   left ~40 threads competing for the CPU, which delayed every response.
# Threads waiting on the lock are idle, so the server stays responsive.
# Running several requests at once comes from uvicorn worker processes
# (WEB_CONCURRENCY in the Dockerfile), each with its own models and lock.
_model_lock = threading.Lock()
_face_detector = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5)
_face_mesh_static = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, min_detection_confidence=0.5)


def detect_face(image_array):
    """
    Detect faces in an image using MediaPipe.

    TODO: Implement using:
    - mediapipe.solutions.face_detection.FaceDetection
    - Return detection results with confidence scores

    Consider setting min_detection_confidence=0.5

    ---
    Implemented: uses mediapipe.solutions.face_detection.FaceDetection with
    min_detection_confidence=0.5. Returns the highest-confidence detection
    result (with its confidence score), or None if no face was detected.
    Uses the process-wide _face_detector under _model_lock (built once at
    import) rather than constructing a detector on every call.
    """
    with _model_lock:
        results = _face_detector.process(image_array)

    if not results.detections:
        return None

    return max(results.detections, key=lambda detection: detection.score[0])


_FACE_MESH_LANDMARK_COUNT = 468  # total landmarks in a complete MediaPipe FaceMesh result

# --- Identity embedding (dlib, via face_recognition) ---
#
# Two prior MediaPipe-landmark-based approaches (raw per-landmark
# coordinates, then normalized pairwise distances between up to ~54
# anatomical points) both failed to separate two different real people
# (obama.jpg vs biden.jpg in tests/public/test_face_recognition.py) -
# empirically verified (see git history / diagnose_embedding.py) their
# raw cosine similarity was ~0.999 for EVERY pair tested, same-person or
# not. MediaPipe FaceMesh simply wasn't built for identity discrimination.
#
# dlib's face_recognition, by contrast, gives a purpose-trained 128-d
# embedding with real separation: obama-vs-obama2/3 (same person) sits at
# cosine similarity ~0.97, obama-vs-biden (different) at ~0.82 - verified
# directly against these sample images before switching.
_DLIB_EMBEDDING_DIM = 128

# dlib's face_encodings are NOT unit-length - measured norm is consistently
# ~1.38 across sample photos (see diagnose_dlib.py). SimHash only ever
# preserves the *direction* of a vector (sign(r.a) is invariant to scaling
# a), so reconstructing a euclidean distance from the hash alone requires
# assuming some typical norm for both vectors, since magnitude itself
# can't be recovered from the hash. This is that assumption.
_ASSUMED_EMBEDDING_NORM = 1.38

# dlib's own documented default (face_recognition/api.py: compare_faces's
# `tolerance` parameter, "0.6 is typical best performance") - a euclidean
# distance, not a similarity score. This is the actual pass/fail decision
# boundary for /face/verify (see verify_face), not our match_score.
_DLIB_EUCLIDEAN_MATCH_THRESHOLD = 0.6

_SIMHASH_BITS = 256  # 256 bits = 32 bytes = exactly 64 hex characters once packed
_SIMHASH_PLANES = np.random.RandomState(42).randn(_SIMHASH_BITS, _DLIB_EMBEDDING_DIM)


def extract_face_embedding(image_array, detection):
    """
    Extract face embedding/features for hashing.

    TODO: Choose your approach:
    - Simple: Crop face region, resize to standard size, flatten
    - Advanced: Use MediaPipe Face Mesh landmarks
    - Even more advanced: Use face recognition model (dlib, etc.)

    Return numpy array that can be hashed.

    ---
    Implemented: the "Even more advanced" option (dlib, via the
    face_recognition package) - see the module-level comment above
    _DLIB_EMBEDDING_DIM for why: two MediaPipe-landmark-based attempts
    were tried first and both empirically failed to discriminate real
    people, which a purpose-trained embedding actually does.

    `detection` (from detect_face) supplies the face box: it's passed to
    face_recognition.face_encodings() as known_face_locations, so dlib
    skips its own face detector, which was ~60-85% of each request's time
    (0.8-2.3s per image vs a steady ~0.35s with the box). Measured on the
    sample images before switching: same-person distances stayed at
    0.33-0.43 and obama-vs-biden at 0.81-0.87 (threshold 0.6), and the same
    image's embedding moved only 0.04-0.07 between the two box sources, so
    templates enrolled with dlib's own detector still match. If MediaPipe's
    box is unusable (degenerate after clamping to the image), dlib's own
    detector is used as before.

    Returns None if no face can be encoded.

    The dlib call runs under _model_lock, since its models are shared
    module-level objects that aren't safe to use from several threads at
    once.
    """
    face_box = _dlib_face_box(image_array, detection)
    with _model_lock:
        if face_box is not None:
            encodings = face_recognition.face_encodings(image_array, known_face_locations=[face_box])
        else:
            encodings = face_recognition.face_encodings(image_array)
    if not encodings:
        return None
    return encodings[0]


def _dlib_face_box(image_array, detection):
    """
    Convert a MediaPipe detection into dlib's (top, right, bottom, left) pixel
    box, clamped to the image. MediaPipe gives a box relative to image size
    that can extend past the edges for faces partly out of frame. Returns
    None if there's no detection or the clamped box has no area.
    """
    if detection is None:
        return None
    height, width = image_array.shape[:2]
    box = detection.location_data.relative_bounding_box
    top = max(0, int(box.ymin * height))
    left = max(0, int(box.xmin * width))
    bottom = min(height, int((box.ymin + box.height) * height))
    right = min(width, int((box.xmin + box.width) * width))
    if bottom <= top or right <= left:
        return None
    return (top, right, bottom, left)


def generate_face_hash(embedding) -> str:
    """
    Generate SHA-256 hash of face embedding.

    TODO: Implement using:
    - hashlib.sha256()
    - embedding.tobytes() or embedding.tostring()
    - Return 64-character hex string

    ---
    Implemented with SimHash instead of SHA-256 — this is a deliberate
    team decision, documented in
    module2-backend/api-docs/API-FOR-FACE-RECOGNITION.md and explained in
    context-pdfs/Module3-FaceRecognition-Design.pdf: SHA-256's avalanche
    effect means two photos of the same face (slightly different
    embeddings) hash to completely unrelated values, so /face/verify could
    never produce a real match. Module 2 stores this value as an opaque
    VARCHAR(64) and doesn't care which scheme produced it, only that it's
    a stable, comparable string that fits in 64 characters.

    Normalizes the embedding to unit length first (dlib's encodings aren't
    already unit-length - see _ASSUMED_EMBEDDING_NORM), then projects onto
    _SIMHASH_BITS (256) fixed random hyperplanes (seeded, so the same
    planes are used for every call) and records the sign of each
    projection as a bit. Two embeddings from the same face land on the
    same side of most hyperplanes (small Hamming distance); different
    faces differ in many more bits.

    256 raw bits would be a 256-character '0'/'1' string, blowing past
    module2's 64-character storage limit - packed into hex instead (4
    bits/character) to fit exactly: 256 bits = 32 bytes = 64 hex chars.
    This is strictly a storage encoding, not a change to the underlying
    SimHash bit count. Comparison (Hamming distance on the *bits*, not
    the hex characters - see _hamming_distance) + threshold happens in
    /face/verify.
    """
    normalized = embedding / np.linalg.norm(embedding)
    projections = _SIMHASH_PLANES @ normalized
    bits = "".join("1" if p > 0 else "0" for p in projections)
    return format(int(bits, 2), "064x")


def _hamming_distance(hash_a: str, hash_b: str) -> int:
    """
    Count differing bits between two hex-encoded SimHash strings (see
    generate_face_hash).

    Decodes both hex strings back to integers and XORs them - comparing
    hex *characters* directly would be wrong (e.g. hex '0' vs '1' differ
    by 1 bit, but '0' vs 'f' differ by 4 bits; equal counts of differing
    characters don't mean equal counts of differing bits).

    Raises ValueError if the two hashes aren't the same length, or aren't
    valid hex - either way they're not comparable (e.g. a malformed/empty
    reference hash stored from a failed enrollment), rather than letting
    Python's arbitrary-precision int silently zero-pad a shorter hash and
    return a misleading distance.
    """
    if len(hash_a) != len(hash_b):
        raise ValueError(
            f"Hash length mismatch: {len(hash_a)} vs {len(hash_b)}"
        )
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")


def analyze_face_mesh(image_array):
    """
    Analyze face using MediaPipe Face Mesh (BONUS).

    TODO: Implement using:
    - mediapipe.solutions.face_mesh.FaceMesh
    - Extract 468 landmarks
    - Calculate depth from nose_tip_z (landmark index 1)
    - Check mesh completeness

    Return dict with:
    - face_mesh_complete: bool
    - landmark_count: int
    - nose_tip_z: float
    - depth_quality: "good" | "moderate" | "poor"

    ---
    Implemented per the docstring above, using this file's own |nose_tip_z|
    thresholds (0.03 "good", 0.01 "moderate") rather than
    docs/API-SPECIFICATION.md's differently-shaped "z < -0.05" signed
    threshold - the two docs don't actually agree on this number, and this
    function's own docstring is the more direct instruction for it.
    Runs on the full image (not a pre-cropped region), unlike
    extract_face_embedding, since check_liveness calls this directly on
    the decoded image. Uses the process-wide _face_mesh_static under
    _model_lock (built once at import).
    """
    with _model_lock:
        results = _face_mesh_static.process(image_array)

    if not results.multi_face_landmarks:
        return {
            "face_mesh_complete": False,
            "landmark_count": 0,
            "nose_tip_z": 0.0,
            "depth_quality": "poor",
        }

    landmarks = results.multi_face_landmarks[0].landmark
    nose_tip_z = float(landmarks[1].z)
    landmark_count = len(landmarks)
    abs_z = abs(nose_tip_z)

    if abs_z > 0.03:
        depth_quality = "good"
    elif abs_z > 0.01:
        depth_quality = "moderate"
    else:
        depth_quality = "poor"

    return {
        "face_mesh_complete": landmark_count >= _FACE_MESH_LANDMARK_COUNT,
        "landmark_count": landmark_count,
        "nose_tip_z": nose_tip_z,
        "depth_quality": depth_quality,
    }


# MediaPipe FaceMesh landmark indices
_NOSE_TIP = 1
_FACE_EDGES = (234, 454)  # outermost cheek point on each side of the face
# Per eye, the six points of the eye-aspect-ratio formula (Soukupova & Cech
# 2016): outer corner, two upper-lid points, inner corner, two lower-lid
# points.
_EYES = ((33, 160, 158, 133, 153, 144), (362, 385, 387, 263, 373, 380))


def _eye_aspect_ratio(points):
    """
    Height of the eye opening over its width, from six pixel points
    (p1..p6 as in _EYES): roughly 0.25-0.35 open, under 0.15 closed.
    """
    p1, p2, p3, p4, p5, p6 = points
    width = np.linalg.norm(p1 - p4)
    if width == 0:
        return 0.0
    return float((np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)) / (2 * width))


def _frame_features(image_array):
    """
    Per-frame measurements for a frame burst, or None if FaceMesh finds no
    face in the frame.

    yaw: horizontal offset of the nose tip from the midpoint between the two
    face edges, divided by the face's width. About 0 when facing the camera,
    positive when the nose points toward the image's right (see
    _YAW_SIGN_STUDENT_LEFT for which way that is for the student). A 2D ratio
    rather than a full 3D pose estimate: comparing turns within one burst
    only needs direction and relative size.

    ear: eye aspect ratio averaged over both eyes, from pixel coordinates
    (landmarks are normalized separately in x and y, so they're scaled back
    first or a non-square frame would distort the ratio).
    """
    with _model_lock:
        results = _face_mesh_static.process(image_array)
    if not results.multi_face_landmarks:
        return None

    landmarks = results.multi_face_landmarks[0].landmark
    left_x, right_x = sorted(landmarks[i].x for i in _FACE_EDGES)
    face_width = right_x - left_x
    if face_width <= 0:
        return None
    yaw = (landmarks[_NOSE_TIP].x - (left_x + right_x) / 2) / face_width

    height, width = image_array.shape[:2]

    def pixel(index):
        return np.array([landmarks[index].x * width, landmarks[index].y * height])

    ear = float(np.mean([_eye_aspect_ratio([pixel(i) for i in eye]) for eye in _EYES]))
    return {"yaw": yaw, "ear": ear}


# --- Challenge step detection (frame bursts) ---
#
# Starting values, not yet tuned on real recordings: re-check them against
# recorded bursts before relying on challenge_passed. A missed step only
# means a retry or review for the student (never a rejection), but a step
# credited when it wasn't done weakens the check.

# Blink: eyes count as closed below this share of the student's own open-eye
# EAR, and as open again above the second share. Relative to the student, not
# a fixed EAR, since eye shape varies between people.
_BLINK_CLOSED_RATIO = 0.6
_BLINK_OPEN_RATIO = 0.85
# Share of a burst's face frames assumed to show open eyes when estimating
# the student's open-eye EAR (its 80th percentile).
_OPEN_EAR_PERCENTILE = 80

# Turn: yaw must move at least this far from where the step started, then
# give back at least this share of the furthest turn ("then back toward
# centre", API-FOR-FACE-RECOGNITION.md §3).
_TURN_MIN_YAW = 0.15
_TURN_RETURN_FRACTION = 0.4
# Frames are raw (not mirrored): the student's left is the image's right, so
# a turn to the student's left should move the nose toward the image's right
# (+yaw). NOT YET CONFIRMED with a real recording; flip to -1 if it reads the
# other way.
_YAW_SIGN_STUDENT_LEFT = 1

# Fewer frames with a face than this per step: not enough to judge, so
# challenge_passed stays None instead of a confident False.
_MIN_FACE_FRAMES_PER_STEP = 3


def detect_blink(frame_features, start, open_ear):
    """
    Detect eye blink from face mesh landmarks (BONUS).

    TODO: Implement using:
    - Eye landmark indices (see MediaPipe docs)
    - Calculate Eye Aspect Ratio (EAR)
    - EAR < threshold indicates closed eye

    ---
    Implemented across a frame burst rather than one image (one image can't
    show a blink). `frame_features` is the burst's per-frame list from
    _frame_features (None where no face was found, ignored here); `open_ear`
    is the student's open-eye EAR. Looks from index `start` for eyes open,
    then at least one closed frame, then open again, and returns the index
    of the frame where they're open again, or None. One closed frame is
    enough on purpose: at ~5 fps a normal blink often lands in a single
    frame.
    """
    closed_below = open_ear * _BLINK_CLOSED_RATIO
    open_above = open_ear * _BLINK_OPEN_RATIO
    seen_open = seen_closed = False
    for index in range(start, len(frame_features)):
        features = frame_features[index]
        if features is None:
            continue
        ear = features["ear"]
        if not seen_open:
            seen_open = ear >= open_above
        elif not seen_closed:
            seen_closed = ear < closed_below
        elif ear >= open_above:
            return index
    return None


def detect_head_turn(frame_features, start, direction):
    """
    Look from index `start` for a head turn and the return toward centre.
    `direction` is +1 for a turn to the student's left, -1 for their right,
    already multiplied by _YAW_SIGN_STUDENT_LEFT by the caller.

    The step's starting yaw is the first face frame at or after `start` (for
    a later step, the frame where the previous step ended). The turn counts
    once yaw has moved at least _TURN_MIN_YAW in `direction` and then come
    back by at least _TURN_RETURN_FRACTION of the furthest point. Returns
    the index of that return frame, or None. Turning the wrong way never
    counts.
    """
    origin = None
    furthest = 0.0
    for index in range(start, len(frame_features)):
        features = frame_features[index]
        if features is None:
            continue
        if origin is None:
            origin = features["yaw"]
            continue
        moved = (features["yaw"] - origin) * direction
        if moved > furthest:
            furthest = moved
        elif furthest >= _TURN_MIN_YAW and moved <= furthest * (1 - _TURN_RETURN_FRACTION):
            return index
    return None


def _detect_step(action, frame_features, start, open_ear):
    """Dispatch one challenge action; an unknown action counts as not performed
    (API-FOR-FACE-RECOGNITION.md §3), so it returns None."""
    if action == "blink":
        return detect_blink(frame_features, start, open_ear)
    if action == "turn_left":
        return detect_head_turn(frame_features, start, _YAW_SIGN_STUDENT_LEFT)
    if action == "turn_right":
        return detect_head_turn(frame_features, start, -_YAW_SIGN_STUDENT_LEFT)
    return None


def evaluate_challenge(frame_features, sequence):
    """
    Check a burst against a challenge sequence. Returns (challenge_passed,
    steps_passed):

    - (None, None) when there's too little to judge: no sequence, or fewer
      than _MIN_FACE_FRAMES_PER_STEP face frames per step. The backend
      treats None as unverified, so a bad camera never costs a student an
      attempt.
    - Otherwise steps_passed has one bool per step in sequence order.
      Steps must happen in order: each step is searched for only after the
      previous one ended, and once a step fails, every later step is False
      too (it can't have happened "in order"). The backend tells the
      student to redo the first False step.
    """
    faces = [features for features in frame_features if features is not None]
    if not sequence or len(faces) < _MIN_FACE_FRAMES_PER_STEP * len(sequence):
        return None, None

    open_ear = float(np.percentile([features["ear"] for features in faces], _OPEN_EAR_PERCENTILE))
    steps_passed = []
    cursor = 0
    for action in sequence:
        end = _detect_step(action, frame_features, cursor, open_ear) if all(steps_passed) else None
        steps_passed.append(end is not None)
        if end is not None:
            cursor = end
    return all(steps_passed), steps_passed


_VPN_USER_AGENT_PATTERN = re.compile(r"vpn|proxy|tunnel|\btor\b", re.IGNORECASE)


def detect_vpn_proxy(ip_address: str, user_agent: str) -> tuple:
    """
    Detect VPN/proxy usage.

    TODO: Check for:
    - Private IP ranges (10.x, 172.16-31.x, 192.168.x)
    - Localhost (127.x, ::1)
    - VPN keywords in user_agent
    - Known proxy headers (not available here, but could extend)

    Return (is_vpn: bool, confidence: float)

    ---
    Only the user-agent keyword check is implemented. Private and loopback
    IPs (the first two bullets) are deliberately NOT treated as VPN signs,
    superseding this starter TODO:
    - The course's later clarification says private/local addresses
      (192.168.x, 10.x, 127.x) "may be treated as on-campus and allowed".
    - module2-backend asks for the same (CHANGES-2026-10-01.md, Module 3
      §A): inside docker-compose every request reaches us from a private
      172.x address, so flagging them added VPN risk to every genuine
      check-in.
    Whether a public IP is outside Singapore is checked by the backend
    (GeoIP) before it calls us, so nothing here looks at the IP at all;
    `ip_address` stays in the signature for callers and future checks.

    "tor" must be a whole word: as a plain substring it matched ordinary
    user agents, e.g. Android phones that include "motorola" in their user
    agent. "vpn", "proxy" and "tunnel" are still matched anywhere, so
    "vpn-client" and "myvpnapp" both count.
    """
    is_vpn = False
    confidence = 0.0

    if user_agent and _VPN_USER_AGENT_PATTERN.search(user_agent):
        is_vpn = True
        confidence = 0.8

    return is_vpn, confidence


# =============================================================================
# PRIVACY REQUIREMENTS (IMPORTANT!)
# =============================================================================
"""
Your implementation MUST follow these privacy requirements:

1. NO RAW IMAGES STORED
   - Process images in-memory only
   - Do not write images to disk
   - Do not send images to external APIs

2. HASH-ONLY STORAGE
   - Store only SHA-256 hashes (64 hex characters)
   - Hashes are one-way - cannot reconstruct face
   - Different faces must produce different hashes

3. EPHEMERAL PROCESSING
   - Clear image data after processing
   - No caching of raw biometric data
   - Use Python's memory management (del, gc.collect)

4. CONSENT TRACKING
   - Require camera_consent=True for enrollment
   - Log consent in audit trail (backend responsibility)

5. RESPONSE HYGIENE
   - Never include base64 image data in responses
   - Only return hashes, scores, and metadata
"""
