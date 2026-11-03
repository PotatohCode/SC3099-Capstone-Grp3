"""
SAIV Face Recognition & Risk Service - Module 3

Face enrolment, verification, liveness (passive anti-spoofing and active
challenges) and risk scoring. Images are processed in memory only; only
face template hashes leave the service. History: ../CHANGES.md.
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
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps
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

# No CORS: only the backend and tests call this service (server to server), so
# browsers keep the same-origin rule (audit 2026-11-02, X-07).


@app.exception_handler(RequestValidationError)
async def validation_error_without_input(request: Request, exc: RequestValidationError):
    """FastAPI's 422 without each error's "input", which would echo the face image back."""
    errors = [{key: value for key, value in error.items() if key != "input"} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


# =============================================================================
# METRICS (GET /metrics, scraped by module4-observability/prometheus.yml)
# =============================================================================
#
# Names and labels are queried by Module 4's dashboard (module4-observability/
# README.md) - don't rename without checking it. With PROMETHEUS_MULTIPROC_DIR
# set (Dockerfile), /metrics sums all worker processes.

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
    "face_verify_total", "Face verifications; result = match / no_match / uncertain / not_compared", ["result"],
)
liveness_checks_total = Counter(
    "liveness_checks_total", "Liveness checks; result = pass / fail / not_assessed", ["result"],
)
face_enroll_total = Counter("face_enroll_total", "Successful face enrollments")


class MetricsMiddleware(BaseHTTPMiddleware):
    """Request count and latency per route template ("unmatched" for unknown URLs)."""

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
    """Decorator: call record(response) after the endpoint returns (keeps counting out of early returns)."""
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
    if response.match_passed is None and response.match_score > 0:
        result = "uncertain"  # compared, but borderline (only "couldn't compare" scores 0.0)
    face_verify_total.labels(result=result).inc()


def _record_liveness(response):
    """One verdict per check, the way the backend reads it: fail, pass or not_assessed."""
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
    # None = not compared, or borderline: the backend rejects on False.
    match_passed: Optional[bool]
    match_score: float  # 0.0 to 1.0
    match_threshold: float  # Default: 0.70
    face_detected: bool
    current_template_hash: str


class LivenessRequest(BaseModel):
    """
    Two shapes (API-FOR-FACE-RECOGNITION.md §3): (a) one image in
    challenge_response; (b) a burst in `frames` (oldest first), plus
    `challenge_sequence` when the backend issued a challenge.
    """
    challenge_response: str  # Base64 encoded image
    challenge_type: str = "passive"  # free text: the backend forwards labels it doesn't validate
    frames: Optional[List[str]] = None
    challenge_sequence: Optional[List[str]] = None  # e.g. ["blink", "turn_left"]


class LivenessResponse(BaseModel):
    """Response model for liveness check."""
    # None = couldn't assess; False only for a determined spoof (the backend rejects on it).
    liveness_passed: Optional[bool]
    liveness_score: float  # 0.0 to 1.0
    liveness_threshold: float  # Default: 0.60
    challenge_type: Optional[str] = None  # echoes the request's, as in the spec's example
    face_embedding_hash: str
    details: Dict[str, Any]
    # Bursts with a challenge_sequence only: steps done in order? None = couldn't tell.
    challenge_passed: Optional[bool] = None
    steps_passed: Optional[List[bool]] = None  # per step, in sequence order


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
    """Prometheus metrics (a plain route: a mounted app would redirect /metrics to /metrics/)."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def root():
    """List available endpoints (bare paths: the public tests check list membership)."""
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

# quality_score heuristics (not spec'd)
_QUALITY_RESOLUTION_BASELINE_PX = 640 * 480  # "good enough" webcam resolution
_QUALITY_FACE_AREA_RATIO_TARGET = 0.15  # face covering ~15% of frame -> full marks


@app.post("/face/enroll", response_model=FaceEnrollResponse, status_code=201)
@_record_result(_record_enroll)
def enroll_face(request: FaceEnrollRequest):
    """
    Enroll a user's face for future verification.

    Failures return 201 with enrollment_successful=False and a
    details.reason (camera_consent_required, invalid_image: ...,
    no_face_detected, spoof_detected), not a 4xx: the backend treats any
    non-2xx as the service being down.

    Anti-spoofing refuses both "spoof" and "suspect" (stricter than a
    check-in): every later check-in is compared with this face, and a
    refused student just tries again.

    quality_score = mean of detection confidence, resolution (vs 640x480)
    and face size (vs ~15% of the frame).
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

    spoof_check = _anti_spoofing(image_array, detection)
    if spoof_check is not None and spoof_check["verdict"] != "real":
        return FaceEnrollResponse(
            enrollment_successful=False,
            face_template_hash="",
            quality_score=0.0,
            details={
                "face_detected": True,
                "reason": "spoof_detected",
                "anti_spoofing": spoof_check["verdict"],
                "texture_analysis_score": round(spoof_check["real_probability"], 4),
            },
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

    details = {
        "face_detected": True,
        "face_detection_confidence": round(confidence, 4),
        "image_quality": image_quality,
        "anti_spoofing": "not_assessed",
    }
    if spoof_check is not None:
        details.update(anti_spoofing=spoof_check["verdict"],
                       texture_analysis_score=round(spoof_check["real_probability"], 4))

    return FaceEnrollResponse(
        enrollment_successful=True,
        face_template_hash=face_hash,
        quality_score=round(quality_score, 4),
        details=details,
    )


# =============================================================================
# FACE VERIFICATION ENDPOINT (REQUIRED - 4 points in public tests)
# =============================================================================

@app.post("/face/verify", response_model=FaceVerifyResponse)
@_record_result(_record_verify)
def verify_face(request: FaceVerifyRequest):
    """
    Verify a face against an enrolled template.

    No usable image or face, or a reference hash that can't be compared
    (empty, or from the old dlib model): match_passed=None, never False -
    the backend rejects on False, and a blurry photo isn't a different
    person.

    The cosine similarity is estimated from the SimHash Hamming distance
    and mapped so that cosine 0.35 = score 0.70 (the spec's threshold).
    match_passed: True at >= 0.70, None (borderline: review) from
    _UNCERTAIN_SCORE_FROM, False below.
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
        if match_score >= _MATCH_SCORE_THRESHOLD:
            match_passed = True
        elif match_score >= _UNCERTAIN_SCORE_FROM:
            match_passed = None  # borderline: review, not reject
        else:
            match_passed = False
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
    """Legacy alias of /face/verify."""
    return verify_face(request)


# =============================================================================
# LIVENESS DETECTION ENDPOINT (REQUIRED - partial; BONUS for advanced)
# =============================================================================

@app.post("/liveness/check", response_model=LivenessResponse)
@_record_result(_record_liveness)
def check_liveness(request: LivenessRequest):
    """
    Liveness check. A single image (any challenge_type) gets the passive
    check; a frame burst goes to _check_liveness_burst.

    Passive score: mean of detection confidence, quality, depth and mesh
    completeness; liveness_passed = score >= 0.60. Those also look fine for
    a photo of a face, so _anti_spoofing (the spec's texture analysis) can
    only lower the result:
    - "spoof": liveness_passed=False, score at most P(real);
    - "suspect" (unsure, or a close-up screen): None, score capped below 0.60;
    - "real": unchanged.

    No face or an undecodable image: liveness_passed=None, not False - the
    backend rejects on False, which is reserved for a determined spoof.
    """
    if request.frames:
        response = _check_liveness_burst(request)
    else:
        try:
            image_array = decode_base64_image(request.challenge_response)
        except ValueError:
            response = LivenessResponse(
                liveness_passed=None,
                liveness_score=0.0,
                liveness_threshold=0.60,
                face_embedding_hash="",
                details={"face_detected": False, "reason": "invalid_image"},
            )
        else:
            response = _passive_liveness(image_array)
    response.challenge_type = request.challenge_type
    return response


def _passive_liveness(image_array) -> LivenessResponse:
    """Passive liveness on one decoded image (see check_liveness)."""
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
    liveness_passed = liveness_score >= 0.60

    # Anti-spoofing can only lower the result (see check_liveness).
    spoof_check = _anti_spoofing(image_array, detection)
    if spoof_check is not None and spoof_check["verdict"] == "spoof":
        liveness_score = min(liveness_score, spoof_check["real_probability"])
        liveness_passed = False
    elif spoof_check is not None and spoof_check["verdict"] == "suspect":
        liveness_score = min(liveness_score, spoof_check["real_probability"], _SUSPECT_SCORE_CAP)
        liveness_passed = None

    details = {
        "face_detected": True,
        "face_detection_confidence": round(confidence, 4),
        "face_mesh_complete": mesh_result["face_mesh_complete"],
        "landmark_count": mesh_result["landmark_count"],
        "nose_tip_z": mesh_result["nose_tip_z"],
        "depth_quality": mesh_result["depth_quality"],
        "depth_detected": mesh_result["depth_quality"] == "good",
        "threshold": 0.60,
    }
    if spoof_check is not None:
        details.update(
            anti_spoofing=spoof_check["verdict"],
            texture_analysis_score=round(spoof_check["real_probability"], 4),
            sharpness=round(spoof_check["sharpness"], 1),
            moire_peak=round(spoof_check["moire_peak"], 1),
        )
    else:
        details["anti_spoofing"] = "not_assessed"

    return LivenessResponse(
        liveness_passed=liveness_passed,
        liveness_score=round(liveness_score, 4),
        liveness_threshold=0.60,
        face_embedding_hash=face_hash,
        details=details,
    )


def _check_liveness_burst(request: LivenessRequest) -> LivenessResponse:
    """
    A frame burst: undecodable frames are skipped; the passive check runs on
    the most front-facing frame; the challenge (if a sequence was sent) is
    judged across all frames. liveness_passed is True or None, never False:
    a low passive score on one webcam frame isn't proof of a spoof.
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
    Weighted risk fusion (weights and LOW/MEDIUM/HIGH/CRITICAL bands per
    API-SPECIFICATION.md); pass_threshold = risk_score < 0.50.

    Signals missing from the request are left out, and the weights are
    renormalised over the ones present - otherwise absent signals dilute
    the score. signal_breakdown holds each weighted contribution (they sum
    to risk_score). Device: only a PEM-format check, not real attestation.

    async: pure arithmetic, so it doesn't wait for a thread behind the
    image requests under load.
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
# HELPER FUNCTIONS
# =============================================================================

def decode_base64_image(base64_string: str) -> np.ndarray:
    """
    Base64 image -> RGB numpy array; ValueError if it isn't one.
    Whitespace is stripped first (line-wrapped base64), and the EXIF
    orientation applied (phone photos are often stored sideways).
    """
    base64_string = "".join((base64_string or "").split())
    if not base64_string:
        raise ValueError("Image data is empty")

    try:
        image_bytes = base64.b64decode(base64_string, validate=True)
        image = Image.open(BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception as exc:
        raise ValueError(f"Could not decode image: {exc}") from exc

    return np.array(image)


# --- Shared face models (one set per process) ---
#
# Used by one request at a time per process, under _model_lock: MediaPipe
# objects aren't thread-safe, and per-thread copies hung under load. Requests
# run in parallel across uvicorn worker processes (WEB_CONCURRENCY).
_model_lock = threading.Lock()
_face_detector = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5)
_face_mesh_static = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, min_detection_confidence=0.5)
# Frame bursts only: refine_landmarks tracks the eyelids much more closely (blinks).
_face_mesh_refined = mp.solutions.face_mesh.FaceMesh(
    static_image_mode=True, max_num_faces=1, min_detection_confidence=0.5, refine_landmarks=True
)


def detect_face(image_array):
    """The highest-confidence MediaPipe face detection, or None."""
    with _model_lock:
        results = _face_detector.process(image_array)

    if not results.detections:
        return None

    return max(results.detections, key=lambda detection: detection.score[0])


_FACE_MESH_LANDMARK_COUNT = 468  # total landmarks in a complete MediaPipe FaceMesh result

# --- Identity embedding (ArcFace MobileFaceNet, via onnxruntime) ---
#
# insightface's w600k_mbf.onnx (buffalo_s, v0.7). Replaced dlib on 2026-10-30
# (CHANGES.md): faster and far better separation. Licence: non-commercial
# research use only - replace for any commercial deployment.
_MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
_ARCFACE_MODEL_PATH = os.path.join(_MODELS_DIR, "w600k_mbf.onnx")
_EMBEDDING_DIM = 512

# Shared by every ONNX model here (ArcFace, anti-spoofing).
_onnx_options = ort.SessionOptions()
_onnx_options.intra_op_num_threads = 1  # one core per worker process; see _model_lock
_onnx_options.inter_op_num_threads = 1
_arcface = ort.InferenceSession(_ARCFACE_MODEL_PATH, _onnx_options, providers=["CPUExecutionProvider"])
_ARCFACE_INPUT = _arcface.get_inputs()[0].name

# insightface's 112x112 alignment template: both eyes, nose tip, mouth corners.
_ARCFACE_TEMPLATE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                              [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)
# The same 5 points from MediaPipe FaceMesh (eye centre = midpoint of its corners).
_ALIGN_EYES = ((33, 133), (362, 263))  # image's left eye, image's right eye
_ALIGN_NOSE = 4
_ALIGN_MOUTH = (61, 291)  # image's left corner, image's right corner

_SIMHASH_BITS = 240  # 60 hex characters; the last 4 of the 64 are _HASH_VERSION_TAG
_SIMHASH_PLANES = np.random.RandomState(42).randn(_SIMHASH_BITS, _EMBEDDING_DIM)
# Marks ArcFace hashes: an old dlib hash gives "couldn't compare" (None), not
# a wrong "different person", until the student re-enrols.
_HASH_VERSION_TAG = "a1f0"

# Match at estimated cosine >= 0.35 (measured: same person >= 0.52, different <= 0.16).
_ARCFACE_MATCH_COSINE = 0.35
_MATCH_SCORE_THRESHOLD = 0.70  # the spec's match_passed = (match_score >= 0.70)
# From here up to the threshold: borderline -> match_passed None (review).
# Above every different-person score seen (<= 0.44), below same-person (~0.78).
_UNCERTAIN_SCORE_FROM = 0.55


def _match_score(cosine):
    """Cosine -> 0-1 match_score, piecewise linear, with _ARCFACE_MATCH_COSINE at the threshold."""
    if cosine >= _ARCFACE_MATCH_COSINE:
        above = (cosine - _ARCFACE_MATCH_COSINE) / (1 - _ARCFACE_MATCH_COSINE)
        return min(1.0, _MATCH_SCORE_THRESHOLD + (1 - _MATCH_SCORE_THRESHOLD) * above)
    return _MATCH_SCORE_THRESHOLD * max(0.0, cosine) / _ARCFACE_MATCH_COSINE


def _mesh_landmarks(image_array):
    """FaceMesh landmarks of the first face, or None (shared by the embedding and the mesh analysis)."""
    with _model_lock:
        results = _face_mesh_static.process(image_array)
    if not results.multi_face_landmarks:
        return None
    return results.multi_face_landmarks[0].landmark


def extract_face_embedding(image_array, landmarks=None):
    """
    512-d unit ArcFace embedding: align 5 mesh points onto _ARCFACE_TEMPLATE
    (112x112 crop), scale pixels to [-1, 1], run the model. None if no face
    or no usable alignment.
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


# --- Anti-spoofing (MiniFASNet + close-up screen check) ---
#
# MiniFASNetV2 / V1SE (Silent-Face-Anti-Spoofing, Apache-2.0; ONNX from
# github.com/yakhyo/face-anti-spoofing). They judge the face plus its
# surroundings, so they miss a screen held close enough to fill the view -
# the close-up check covers that. Measurements: CHANGES.md 2026-10-30 (2).
_ANTISPOOF_MODELS = (("MiniFASNetV2.onnx", 2.7), ("MiniFASNetV1SE.onnx", 4.0))
_antispoof = [
    (ort.InferenceSession(os.path.join(_MODELS_DIR, name), _onnx_options, providers=["CPUExecutionProvider"]), scale)
    for name, scale in _ANTISPOOF_MODELS
]
_ANTISPOOF_INPUT_SIZE = 80
_ANTISPOOF_MAX_SIDE = 640  # sharpness depends on resolution, so analyse at the size it was tuned on

_ANTISPOOF_SPOOF_BELOW = 0.5  # P(real) under this: "spoof"
_ANTISPOOF_SUSPECT_BELOW = 0.85  # P(real) under this: "suspect" (genuine measured >= 0.89)
# Close-up screen: blurry face AND a moire spike - neither alone (dim light
# blurs and adds noise to genuine faces too).
_CLOSEUP_SHARPNESS_BELOW = 120.0
_CLOSEUP_MOIRE_ABOVE = 30.0
_SUSPECT_SCORE_CAP = 0.5  # a "suspect" image's liveness score, under the 0.60 pass mark

_FFT_SIZE = 128
_FFT_RADIUS = np.hypot(*np.mgrid[-_FFT_SIZE // 2:_FFT_SIZE // 2, -_FFT_SIZE // 2:_FFT_SIZE // 2])
_MOIRE_BAND = (_FFT_RADIUS > 16) & (_FFT_RADIUS < 60)


def _anti_spoofing(image_array, detection):
    """
    Print/screen check: {real_probability (both models averaged), sharpness,
    moire_peak, verdict: "spoof" / "suspect" / "real"}, or None if the face
    box is unusable.
    """
    height, width = image_array.shape[:2]
    if max(height, width) > _ANTISPOOF_MAX_SIDE:
        factor = _ANTISPOOF_MAX_SIDE / max(height, width)
        image_array = cv2.resize(image_array, (round(width * factor), round(height * factor)),
                                 interpolation=cv2.INTER_AREA)
        height, width = image_array.shape[:2]
    box = detection.location_data.relative_bounding_box
    x, y = int(box.xmin * width), int(box.ymin * height)
    w, h = int(box.width * width), int(box.height * height)
    if w <= 0 or h <= 0:
        return None

    bgr = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)  # the models were trained on BGR, 0-255
    probabilities = np.zeros(3)
    for session, scale in _antispoof:
        crop = _antispoof_crop(bgr, (x, y, w, h), scale)
        blob = crop.astype(np.float32).transpose(2, 0, 1)[np.newaxis]
        with _model_lock:
            logits = session.run(None, {session.get_inputs()[0].name: blob})[0][0]
        exp = np.exp(logits - logits.max())
        probabilities += exp / exp.sum()
    real_probability = float(probabilities[1] / len(_antispoof))

    face = image_array[max(0, y):min(height, y + h), max(0, x):min(width, x + w)]
    if face.size == 0:
        return None
    gray = cv2.cvtColor(cv2.resize(face, (_FFT_SIZE, _FFT_SIZE), interpolation=cv2.INTER_AREA),
                        cv2.COLOR_RGB2GRAY).astype(np.float32)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(gray - gray.mean())))[_MOIRE_BAND]
    moire_peak = float(spectrum.max() / (np.median(spectrum) + 1e-6))

    if real_probability < _ANTISPOOF_SPOOF_BELOW:
        verdict = "spoof"
    elif real_probability < _ANTISPOOF_SUSPECT_BELOW or (
        sharpness < _CLOSEUP_SHARPNESS_BELOW and moire_peak > _CLOSEUP_MOIRE_ABOVE
    ):
        verdict = "suspect"
    else:
        verdict = "real"
    return {"real_probability": real_probability, "sharpness": sharpness, "moire_peak": moire_peak,
            "verdict": verdict}


def _antispoof_crop(bgr, box, scale):
    """Face box enlarged `scale` times, clamped to the image, resized to 80x80 (Silent-Face's CropImage)."""
    src_h, src_w = bgr.shape[:2]
    x, y, w, h = box
    scale = min((src_h - 1) / h, (src_w - 1) / w, scale)
    center_x, center_y = x + w / 2, y + h / 2
    new_w, new_h = w * scale, h * scale
    x1, y1 = max(0, int(center_x - new_w / 2)), max(0, int(center_y - new_h / 2))
    x2, y2 = min(src_w - 1, int(center_x + new_w / 2)), min(src_h - 1, int(center_y + new_h / 2))
    return cv2.resize(bgr[y1:y2 + 1, x1:x2 + 1], (_ANTISPOOF_INPUT_SIZE, _ANTISPOOF_INPUT_SIZE))


def generate_face_hash(embedding) -> str:
    """
    SimHash, not SHA-256 (team decision): SHA-256 gives unrelated values for
    two photos of the same face, so nothing could ever match. The sign of
    the embedding's projection on 240 fixed random planes, as 60 hex chars,
    plus _HASH_VERSION_TAG = 64 lowercase hex.
    """
    normalized = embedding / np.linalg.norm(embedding)
    projections = _SIMHASH_PLANES @ normalized
    bits = "".join("1" if p > 0 else "0" for p in projections)
    return format(int(bits, 2), f"0{_SIMHASH_BITS // 4}x") + _HASH_VERSION_TAG


def _hamming_distance(hash_a: str, hash_b: str) -> int:
    """
    Differing bits between two SimHash hashes (tag excluded). ValueError if
    they can't be compared: different lengths, not hex, or no
    _HASH_VERSION_TAG (an old dlib hash).
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
    Mesh completeness and depth from nose_tip_z (|z| > 0.03 good, > 0.01
    moderate - the starter's rule). MediaPipe predicts z from the 2D image,
    so a flat photo gets depth too; prints are caught by _anti_spoofing.
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
# Per eye, the six eye-aspect-ratio points (Soukupova & Cech 2016).
_EYES = ((33, 160, 158, 133, 153, 144), (362, 385, 387, 263, 373, 380))


def _eye_aspect_ratio(points):
    """Eye opening height over width (~0.25-0.35 open, < 0.15 closed)."""
    p1, p2, p3, p4, p5, p6 = points
    width = np.linalg.norm(p1 - p4)
    if width == 0:
        return 0.0
    return float((np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)) / (2 * width))


def _frame_features(image_array):
    """
    Per-frame burst measurements, or None if no face:
    - yaw: nose offset from the face's centre / face width (0 = facing the
      camera, positive = nose toward the image's right);
    - ear: eye aspect ratio of both eyes, in pixels;
    - face_width: face width as a share of the frame width.
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
# Tuned on real recordings (CHANGES.md 2026-10-24). A missed step means a
# retry or review, never a rejection.

# Blink: closed below / open above these shares of the student's own open-eye
# EAR (eye shapes differ). 0.33 caught the most blinks without counting squints.
_BLINK_CLOSED_RATIO = 0.33
_BLINK_OPEN_RATIO = 0.85
_OPEN_EAR_PERCENTILE = 80  # the student's open-eye EAR = this percentile of the burst
# Eyes are only judged facing the camera (a turned head inflates EAR) and when
# the face is big enough (a small face's EAR is noise that looks like a blink).
_BLINK_MAX_YAW = 0.25
_BLINK_MIN_FACE_WIDTH = 0.2

# Turn: yaw moves at least this far, then gives back this share ("then back toward centre").
_TURN_MIN_YAW = 0.15
_TURN_RETURN_FRACTION = 0.4
# Raw (unmirrored) frames: the student's left is +yaw (confirmed on recordings).
_YAW_SIGN_STUDENT_LEFT = 1

# Fewer face frames than this per step: challenge_passed None, not False.
_MIN_FACE_FRAMES_PER_STEP = 3


def _eyes_measurable(features):
    """Can this frame's eyes be judged (facing the camera, face big enough)?"""
    return (
        features is not None
        and abs(features["yaw"]) <= _BLINK_MAX_YAW
        and features["face_width"] >= _BLINK_MIN_FACE_WIDTH
    )


def open_eye_ear(frame_features):
    """The student's open-eye EAR over the measurable frames, or None."""
    ears = [features["ear"] for features in frame_features if _eyes_measurable(features)]
    return float(np.percentile(ears, _OPEN_EAR_PERCENTILE)) if ears else None


def detect_blink(frame_features, start, open_ear):
    """
    From index `start`: eyes open, closed (one frame is enough at ~5 fps),
    open again. Returns the index where they reopen, or None.
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
    From index `start`: yaw moves >= _TURN_MIN_YAW in `direction` (+1 =
    student's left after the sign fix), then back by _TURN_RETURN_FRACTION.
    Returns the index of the return frame, or None.
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
    """One challenge action; an unknown action counts as not performed."""
    if action == "blink":
        return detect_blink(frame_features, start, open_ear)
    if action == "turn_left":
        return detect_head_turn(frame_features, start, _YAW_SIGN_STUDENT_LEFT)
    if action == "turn_right":
        return detect_head_turn(frame_features, start, -_YAW_SIGN_STUDENT_LEFT)
    return None


def evaluate_challenge(frame_features, sequence):
    """
    (challenge_passed, steps_passed) for a burst. (None, None) if too few
    face frames to judge. Steps must happen in order: after a failed step,
    every later one is False.
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
    (is_vpn, confidence) from VPN keywords in the user agent ("tor" as a
    whole word, so "motorola" doesn't match). Private/local IPs are not VPN
    signs (course clarification; in Docker every request comes from 172.x),
    and the backend checks public IPs' country itself.
    """
    is_vpn = False
    confidence = 0.0

    if user_agent and _VPN_USER_AGENT_PATTERN.search(user_agent):
        is_vpn = True
        confidence = 0.8

    return is_vpn, confidence
