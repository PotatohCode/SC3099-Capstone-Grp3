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

import cv2
import mediapipe as mp
import numpy as np
import onnxruntime as ort
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
# Names and labels follow the spec in module4-observability/README.md ("Face
# service metrics (for Module 3)"), which its System Health dashboard
# queries. Don't rename without checking that dashboard. Extra label values
# (not_compared, not_assessed) don't break its queries.
#
# None of these reuse the backend's http_request_duration_seconds: the same
# dashboard sums that name across every scrape job, so face-service latency
# would be mixed into the backend's API panels.
#
# Each uvicorn worker process keeps its own counters, and a scrape reaches only
# one worker. When PROMETHEUS_MULTIPROC_DIR is set (the Dockerfile sets it),
# prometheus_client writes every worker's values into that folder and /metrics
# reports their sum. Without it (e.g. a local single-process run), the normal
# in-process registry is used.

face_requests_total = Counter(
    "face_requests_total", "Face service requests", ["endpoint", "status"],
)
face_request_duration_seconds = Histogram(
    "face_request_duration_seconds",
    "Face service request latency in seconds",
    ["endpoint"],
    # 5 s and 15 s are the backend's timeouts (single image / frame burst).
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 15, 30, 60),
)
face_verify_total = Counter(
    "face_verify_total", "Face verifications; result = match / no_match / not_compared", ["result"],
)
liveness_checks_total = Counter(
    "liveness_checks_total", "Liveness checks; result = pass / fail / not_assessed", ["result"],
)
face_enroll_total = Counter("face_enroll_total", "Successful face enrollments")


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Records face_requests_total and face_request_duration_seconds for every
    request. The endpoint label is the route template (e.g. "/face/verify"),
    not the raw URL, and requests that match no route are labelled
    "unmatched", so random URLs can't create unbounded label values.
    """

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        endpoint = getattr(route, "path", None) or "unmatched"
        face_requests_total.labels(endpoint=endpoint, status=str(response.status_code)).inc()
        face_request_duration_seconds.labels(endpoint=endpoint).observe(time.perf_counter() - start)
        return response


app.add_middleware(MetricsMiddleware)


def _record_result(record):
    """
    Decorator for a sync endpoint: once it returns, call record(response) to
    update the outcome counters. This keeps counting out of the endpoints'
    many early returns. functools.wraps preserves the endpoint's signature
    and docstring, which FastAPI reads for request parsing and /docs.
    """
    def decorator(endpoint):
        @functools.wraps(endpoint)
        def wrapper(*args, **kwargs):
            response = endpoint(*args, **kwargs)
            record(response)
            return response
        return wrapper
    return decorator


def _record_enroll(response):
    if response.enrollment_successful:
        face_enroll_total.inc()


def _record_verify(response):
    result = {True: "match", False: "no_match"}.get(response.match_passed, "not_compared")
    face_verify_total.labels(result=result).inc()


def _record_liveness(response):
    """
    One verdict per check, the way the backend reads it (checkins.py
    _classify_liveness): fail if the anti-spoof check or the challenge
    failed; pass if liveness passed and, for a burst with a challenge, the
    challenge was actually judged; otherwise not_assessed.
    """
    if response.liveness_passed is False or response.challenge_passed is False:
        result = "fail"
    elif response.liveness_passed is True and response.details.get("challenge") != "insufficient_frames":
        result = "pass"
    else:
        result = "not_assessed"
    liveness_checks_total.labels(result=result).inc()


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
@_record_result(_record_enroll)
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

    embedding = extract_face_embedding(image_array)
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
@_record_result(_record_verify)
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

    Only the hashes are available here, never the raw reference embedding,
    so the cosine similarity of the two embeddings is estimated from the
    Hamming distance between their SimHash values (see _hamming_distance):
    the fraction of differing bits approximates the angle between the
    vectors divided by pi.

    match_score maps that cosine onto 0-1 so that the decision is exactly
    the spec's step 8, match_passed = (match_score >= 0.70): cosine
    _ARCFACE_MATCH_COSINE (0.35) lands on 0.70, 1.0 (identical) on 1.0,
    and 0 or below (unrelated faces) on 0.0, linear in between. Same-person
    pairs measured 0.52-1.0 (score ~0.78-1.0); different people at most
    0.16 (score ~0.32).

    A reference_template_hash that can't be compared - not a valid 64-char
    hex SimHash (e.g. empty string, from a user who never successfully
    enrolled), or one from the earlier dlib model (no _HASH_VERSION_TAG) -
    makes _hamming_distance raise ValueError, treated as "couldn't compare"
    (match_passed=None, match_score=0.0) rather than a crash, since it's an
    expected data state, not a service failure.
    """
    try:
        image_array = decode_base64_image(request.image)
    except ValueError:
        return FaceVerifyResponse(
            match_passed=None,
            match_score=0.0,
            match_threshold=_MATCH_SCORE_THRESHOLD,
            face_detected=False,
            current_template_hash="",
        )

    detection = detect_face(image_array)
    if detection is None:
        return FaceVerifyResponse(
            match_passed=None,
            match_score=0.0,
            match_threshold=_MATCH_SCORE_THRESHOLD,
            face_detected=False,
            current_template_hash="",
        )

    embedding = extract_face_embedding(image_array)
    if embedding is None:
        return FaceVerifyResponse(
            match_passed=None,
            match_score=0.0,
            match_threshold=_MATCH_SCORE_THRESHOLD,
            face_detected=False,
            current_template_hash="",
        )

    current_hash = generate_face_hash(embedding)

    try:
        distance = _hamming_distance(current_hash, request.reference_template_hash)
        estimated_cos_sim = float(np.cos(distance / _SIMHASH_BITS * np.pi))
        match_score = _match_score(estimated_cos_sim)
        match_passed = match_score >= _MATCH_SCORE_THRESHOLD
    except ValueError:
        match_passed = None
        match_score = 0.0

    return FaceVerifyResponse(
        match_passed=match_passed,
        match_score=round(match_score, 4),
        match_threshold=_MATCH_SCORE_THRESHOLD,
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
@_record_result(_record_liveness)
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

    # One mesh run for both the face hash and the depth/completeness signals.
    landmarks = _mesh_landmarks(image_array)
    embedding = extract_face_embedding(image_array, landmarks) if landmarks is not None else None
    face_hash = generate_face_hash(embedding) if embedding is not None else ""

    confidence = float(detection.score[0])
    height, width = image_array.shape[:2]
    resolution_score = min(1.0, (width * height) / _QUALITY_RESOLUTION_BASELINE_PX)
    bbox = detection.location_data.relative_bounding_box
    face_size_score = min(1.0, (bbox.width * bbox.height) / _QUALITY_FACE_AREA_RATIO_TARGET)
    quality_signal = (resolution_score + face_size_score) / 2

    mesh_result = analyze_face_mesh(image_array, landmarks)
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
# - The ArcFace session (_arcface, see extract_face_embedding) is set to one
#   CPU thread, so each worker process uses one core and 3 workers don't
#   fight over the CPUs; under the lock it runs one face at a time.
# - MediaPipe solution objects aren't thread-safe. An earlier version
#   gave each thread its own copy instead; under load that built dozens of
#   models at once after a restart (100 parallel requests hung for 120s) and
#   left ~40 threads competing for the CPU, which delayed every response.
# Threads waiting on the lock are idle, so the server stays responsive.
# Running several requests at once comes from uvicorn worker processes
# (WEB_CONCURRENCY in the Dockerfile), each with its own models and lock.
_model_lock = threading.Lock()
_face_detector = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5)
_face_mesh_static = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, min_detection_confidence=0.5)
# Frame bursts only (_frame_features): refine_landmarks tracks the eyelids far
# more closely. Measured on real recordings, a blink's lowest EAR dropped to a
# median 0.21 of open (squints 0.37-0.53) vs 0.69 with the standard mesh
# (squints 0.70-0.80, overlapping blinks). ~1 ms more per frame. The passive
# check and single images keep _face_mesh_static, so their scores don't change.
_face_mesh_refined = mp.solutions.face_mesh.FaceMesh(
    static_image_mode=True, max_num_faces=1, min_detection_confidence=0.5, refine_landmarks=True
)


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

# --- Identity embedding (ArcFace MobileFaceNet, via onnxruntime) ---
#
# Two prior MediaPipe-landmark-based approaches (raw per-landmark
# coordinates, then normalized pairwise distances between up to ~54
# anatomical points) both failed to separate two different real people
# (obama.jpg vs biden.jpg in tests/public/test_face_recognition.py) -
# empirically verified (see git history / diagnose_embedding.py) their
# raw cosine similarity was ~0.999 for EVERY pair tested, same-person or
# not. MediaPipe FaceMesh simply wasn't built for identity discrimination.
#
# dlib (via face_recognition) replaced them, and was in turn replaced by
# ArcFace on 2026-10-30 (CHANGES.md): ~15 ms per face instead of dlib's
# ~86 ms, and far wider separation. On 45 webcam frames of one person
# (several sessions, glasses on/off) plus the course samples, same-person
# cosine similarity was 0.58-1.0 and different people at most 0.05, vs
# dlib's 0.95-1.0 and 0.87.
#
# Model: insightface's w600k_mbf.onnx (MobileFaceNet trained with ArcFace
# loss on WebFace600K, from the buffalo_s pack, release v0.7). insightface's
# pretrained models are for non-commercial research use only - fine for
# this coursework, but needs replacing for any commercial deployment.
_ARCFACE_MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "models", "w600k_mbf.onnx")
_EMBEDDING_DIM = 512

_arcface_options = ort.SessionOptions()
_arcface_options.intra_op_num_threads = 1  # one core per worker process; see _model_lock
_arcface_options.inter_op_num_threads = 1
_arcface = ort.InferenceSession(_ARCFACE_MODEL_PATH, _arcface_options, providers=["CPUExecutionProvider"])
_ARCFACE_INPUT = _arcface.get_inputs()[0].name

# Where the 5 alignment points land in ArcFace's 112x112 input (insightface's
# standard template, image coordinates): the eye on the image's left, the eye
# on the image's right, nose tip, left and right mouth corners.
_ARCFACE_TEMPLATE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                              [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)
# The same 5 points from MediaPipe FaceMesh (each eye centre = the midpoint of
# its two corners), so no second face detector is needed.
_ALIGN_EYES = ((33, 133), (362, 263))  # image's left eye, image's right eye
_ALIGN_NOSE = 4
_ALIGN_MOUTH = (61, 291)  # image's left corner, image's right corner

_SIMHASH_BITS = 240  # 60 hex characters; the last 4 of the 64 are _HASH_VERSION_TAG
_SIMHASH_PLANES = np.random.RandomState(42).randn(_SIMHASH_BITS, _EMBEDDING_DIM)
# Marks a hash as made by the ArcFace model. Hashes from the earlier dlib
# model (256 random-looking bits) can't be compared with these, and comparing
# them anyway would say "different person" (match_passed: false), which the
# backend flags on every session and rejects on face-required ones. With the
# tag, verify_face answers None ("couldn't compare") for them instead, until
# the student re-enrols. A dlib hash ends in this tag by chance 1 in 65,536
# times.
_HASH_VERSION_TAG = "a1f0"

# /face/verify decision: estimated cosine similarity of the two embeddings.
# Measured (see the comment above _ARCFACE_MODEL_PATH): same person >= 0.52,
# different people <= 0.16 through the hash; 0.35 sits in the middle of that
# gap, and is within insightface's usual 0.3-0.4 for this model.
_ARCFACE_MATCH_COSINE = 0.35
_MATCH_SCORE_THRESHOLD = 0.70  # the spec's match_passed = (match_score >= 0.70)


def _match_score(cosine):
    """
    Map an estimated cosine similarity onto the 0-1 match_score so that
    _ARCFACE_MATCH_COSINE lands exactly on _MATCH_SCORE_THRESHOLD: linear
    from 0 (cosine <= 0) up to the threshold, then linear to 1.0 at
    cosine 1.0. See verify_face.
    """
    if cosine >= _ARCFACE_MATCH_COSINE:
        above = (cosine - _ARCFACE_MATCH_COSINE) / (1 - _ARCFACE_MATCH_COSINE)
        return min(1.0, _MATCH_SCORE_THRESHOLD + (1 - _MATCH_SCORE_THRESHOLD) * above)
    return _MATCH_SCORE_THRESHOLD * max(0.0, cosine) / _ARCFACE_MATCH_COSINE


def _mesh_landmarks(image_array):
    """
    The static FaceMesh's landmarks for the first face, or None if it finds
    no face. Shared by the passive liveness check (analyze_face_mesh) and the
    embedding, so a request that needs both runs the mesh once.
    """
    with _model_lock:
        results = _face_mesh_static.process(image_array)
    if not results.multi_face_landmarks:
        return None
    return results.multi_face_landmarks[0].landmark


def extract_face_embedding(image_array, landmarks=None):
    """
    Extract face embedding/features for hashing.

    TODO: Choose your approach:
    - Simple: Crop face region, resize to standard size, flatten
    - Advanced: Use MediaPipe Face Mesh landmarks
    - Even more advanced: Use face recognition model (dlib, etc.)

    Return numpy array that can be hashed.

    ---
    Implemented: the "Even more advanced" option, with ArcFace (see the
    comment above _ARCFACE_MODEL_PATH for why, and for the model's licence).

    1. Five points from MediaPipe FaceMesh (`landmarks`, from _mesh_landmarks;
       computed here if not given): both eye centres, nose tip, mouth
       corners.
    2. A similarity transform (rotation, scale, shift) maps them onto
       _ARCFACE_TEMPLATE and crops the face to 112x112, the way ArcFace was
       trained: eyes level and at fixed positions.
    3. Pixels scaled to [-1, 1] (RGB, as decode_base64_image returns), run
       through the model under _model_lock.
    4. The 512-d output is normalised to unit length.

    Returns None if the mesh finds no face, or the points don't give a
    usable transform.
    """
    if landmarks is None:
        landmarks = _mesh_landmarks(image_array)
        if landmarks is None:
            return None

    height, width = image_array.shape[:2]

    def point(index):
        return np.array([landmarks[index].x * width, landmarks[index].y * height], dtype=np.float32)

    source = np.stack([
        (point(_ALIGN_EYES[0][0]) + point(_ALIGN_EYES[0][1])) / 2,
        (point(_ALIGN_EYES[1][0]) + point(_ALIGN_EYES[1][1])) / 2,
        point(_ALIGN_NOSE),
        point(_ALIGN_MOUTH[0]),
        point(_ALIGN_MOUTH[1]),
    ])
    transform, _ = cv2.estimateAffinePartial2D(source, _ARCFACE_TEMPLATE, method=cv2.LMEDS)
    if transform is None:
        return None
    face = cv2.warpAffine(image_array, transform, (112, 112), borderValue=0.0)
    blob = ((face.astype(np.float32) - 127.5) / 127.5).transpose(2, 0, 1)[np.newaxis]

    with _model_lock:
        embedding = _arcface.run(None, {_ARCFACE_INPUT: blob})[0][0]
    return embedding / np.linalg.norm(embedding)


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

    Projects the (unit-length) embedding onto _SIMHASH_BITS (240) fixed
    random hyperplanes (seeded, so the same planes are used for every
    call) and records the sign of each projection as a bit. Two embeddings
    from the same face land on the same side of most hyperplanes (small
    Hamming distance); different faces differ in many more bits.

    240 raw bits would be a 240-character '0'/'1' string, blowing past
    module2's 64-character storage limit - packed into hex instead (4
    bits/character): 60 hex chars, then _HASH_VERSION_TAG (4 hex chars) to
    make exactly 64, all lowercase hex like a SHA-256. This is strictly a
    storage encoding, not a change to the underlying SimHash bit count.
    Comparison (Hamming distance on the *bits*, not the hex characters -
    see _hamming_distance) + threshold happens in /face/verify.
    """
    normalized = embedding / np.linalg.norm(embedding)
    projections = _SIMHASH_PLANES @ normalized
    bits = "".join("1" if p > 0 else "0" for p in projections)
    return format(int(bits, 2), f"0{_SIMHASH_BITS // 4}x") + _HASH_VERSION_TAG


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

    Also raises ValueError if either hash lacks _HASH_VERSION_TAG, e.g. one
    enrolled with the earlier dlib model: its bits come from different
    hyperplanes and a different embedding, so a distance would be
    meaningless. Only the bits before the tag are compared.
    """
    if len(hash_a) != len(hash_b):
        raise ValueError(
            f"Hash length mismatch: {len(hash_a)} vs {len(hash_b)}"
        )
    if not (hash_a.endswith(_HASH_VERSION_TAG) and hash_b.endswith(_HASH_VERSION_TAG)):
        raise ValueError("Hash from another face model version")
    bits = slice(0, -len(_HASH_VERSION_TAG))
    return bin(int(hash_a[bits], 16) ^ int(hash_b[bits], 16)).count("1")


def analyze_face_mesh(image_array, landmarks=None):
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
    Runs on the full image (not a pre-cropped region), since check_liveness
    calls this directly on the decoded image. Uses the process-wide
    _face_mesh_static (via _mesh_landmarks, built once at import), unless
    the caller passes `landmarks` it already got from _mesh_landmarks.
    """
    if landmarks is None:
        landmarks = _mesh_landmarks(image_array)

    if landmarks is None:
        return {
            "face_mesh_complete": False,
            "landmark_count": 0,
            "nose_tip_z": 0.0,
            "depth_quality": "poor",
        }

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

    face_width: distance between the two face edges as a share of the frame
    width (how big the face is in the frame).

    Uses _face_mesh_refined (refine_landmarks) for the eyelid accuracy.
    """
    with _model_lock:
        results = _face_mesh_refined.process(image_array)
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
    return {"yaw": yaw, "ear": ear, "face_width": face_width}


# --- Challenge step detection (frame bursts) ---
#
# Starting values, not yet tuned on real recordings: re-check them against
# recorded bursts before relying on challenge_passed. A missed step only
# means a retry or review for the student (never a rejection), but a step
# credited when it wasn't done weakens the check.

# Blink: eyes count as closed below this share of the student's own open-eye
# EAR, and as open again above the second share. Relative to the student, not
# a fixed EAR, since eye shape varies between people. Chosen on 46 real
# recordings (2026-10-24) with the refined eyelid landmarks: genuine blinks'
# lowest EAR was a median 0.21 of open (27 of 29 at or under 0.30), squints
# 0.37-0.53. 0.33 caught the most blinks with no squint counted; 0.40
# started counting squints.
_BLINK_CLOSED_RATIO = 0.33
_BLINK_OPEN_RATIO = 0.85
# Share of a burst's face frames assumed to show open eyes when estimating
# the student's open-eye EAR (its 80th percentile).
_OPEN_EAR_PERCENTILE = 80
# Eyes are only judged on frames facing roughly toward the camera. With the
# head turned, the eye's outline is foreshortened and EAR inflates: measured
# on real recordings, ~0.25 facing the camera vs 0.35-0.45 at yaw ~0.6-1.3
# (0.5-0.6 with the standard mesh), which made normal open eyes read as
# "closed".
_BLINK_MAX_YAW = 0.25
# ...and only when the face is big enough to place the eyelid points
# reliably: face width as a share of the frame width. A face on a phone held
# up to the camera (69-104 px of 640) gave EAR noise of 0.07-0.15 that looked
# like a blink; real faces at arm's length were 183-259 px.
_BLINK_MIN_FACE_WIDTH = 0.2

# Turn: yaw must move at least this far from where the step started, then
# give back at least this share of the furthest turn ("then back toward
# centre", API-FOR-FACE-RECOGNITION.md §3).
_TURN_MIN_YAW = 0.15
_TURN_RETURN_FRACTION = 0.4
# Frames are raw (not mirrored): the student's left is the image's right, so
# a turn to the student's left moves the nose toward the image's right
# (+yaw). Confirmed on real recordings (2026-10-24: turning to one's own left
# read +0.52 to +0.94).
_YAW_SIGN_STUDENT_LEFT = 1

# Fewer frames with a face than this per step: not enough to judge, so
# challenge_passed stays None instead of a confident False.
_MIN_FACE_FRAMES_PER_STEP = 3


def _eyes_measurable(features):
    """True for a frame whose eyes can be judged: a face turned no further
    than _BLINK_MAX_YAW and at least _BLINK_MIN_FACE_WIDTH of the frame wide."""
    return (
        features is not None
        and abs(features["yaw"]) <= _BLINK_MAX_YAW
        and features["face_width"] >= _BLINK_MIN_FACE_WIDTH
    )


def open_eye_ear(frame_features):
    """
    The student's open-eye EAR for a burst: the _OPEN_EAR_PERCENTILE-th
    percentile over frames whose eyes can be judged (_eyes_measurable; most
    of them show open eyes). Turned frames are left out because their EAR is
    inflated, tiny faces because it's noise. None if no frame qualifies.
    """
    ears = [features["ear"] for features in frame_features if _eyes_measurable(features)]
    return float(np.percentile(ears, _OPEN_EAR_PERCENTILE)) if ears else None


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
    _frame_features; `open_ear` is the student's open-eye EAR
    (open_eye_ear). Looks from index `start` for eyes open, then at least
    one closed frame, then open again, and returns the index of the frame
    where they're open again, or None. One closed frame is enough on
    purpose: at ~5 fps a normal blink often lands in a single frame.
    Frames whose eyes can't be judged (no face, turned, or too small - see
    _eyes_measurable) are skipped.
    """
    if open_ear is None:
        return None
    closed_below = open_ear * _BLINK_CLOSED_RATIO
    open_above = open_ear * _BLINK_OPEN_RATIO
    seen_open = seen_closed = False
    for index in range(start, len(frame_features)):
        features = frame_features[index]
        if not _eyes_measurable(features):
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

    open_ear = open_eye_ear(frame_features)
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
