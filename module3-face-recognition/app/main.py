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
from io import BytesIO

import face_recognition
import mediapipe as mp
import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel
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
    match_passed: bool
    match_score: float  # 0.0 to 1.0
    match_threshold: float  # Default: 0.70
    face_detected: bool
    current_template_hash: str


class LivenessRequest(BaseModel):
    """Request model for liveness check."""
    challenge_response: str  # Base64 encoded image
    challenge_type: str = "blink"  # blink, head_turn, passive


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
        ]
    }


# =============================================================================
# FACE ENROLLMENT ENDPOINT (REQUIRED - 4 points in public tests)
# =============================================================================

# quality_score heuristics (not spec'd anywhere - see enroll_face docstring)
_QUALITY_RESOLUTION_BASELINE_PX = 640 * 480  # "good enough" webcam resolution
_QUALITY_FACE_AREA_RATIO_TARGET = 0.15  # face covering ~15% of frame -> full marks


@app.post("/face/enroll", response_model=FaceEnrollResponse, status_code=201)
async def enroll_face(request: FaceEnrollRequest):
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
async def verify_face(request: FaceVerifyRequest):
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
    all treated the same way: face_detected=False, match_passed=False,
    match_score=0.0, current_template_hash="".

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
    ValueError, treated as "no match" (match_score=0.0) rather than a
    crash, since it's an expected data state, not a service failure.
    """
    try:
        image_array = decode_base64_image(request.image)
    except ValueError:
        return FaceVerifyResponse(
            match_passed=False,
            match_score=0.0,
            match_threshold=0.70,
            face_detected=False,
            current_template_hash="",
        )

    detection = detect_face(image_array)
    if detection is None:
        return FaceVerifyResponse(
            match_passed=False,
            match_score=0.0,
            match_threshold=0.70,
            face_detected=False,
            current_template_hash="",
        )

    embedding = extract_face_embedding(image_array, detection)
    if embedding is None:
        return FaceVerifyResponse(
            match_passed=False,
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
        match_passed = False
        match_score = 0.0

    return FaceVerifyResponse(
        match_passed=match_passed,
        match_score=round(match_score, 4),
        match_threshold=0.70,
        face_detected=True,
        current_template_hash=current_hash,
    )


@app.post("/face/match")
async def match_face(request: FaceVerifyRequest):
    """
    Legacy face matching endpoint. Redirects to /face/verify.
    Kept for backwards compatibility.
    """
    return await verify_face(request)


# =============================================================================
# LIVENESS DETECTION ENDPOINT (REQUIRED - partial; BONUS for advanced)
# =============================================================================

@app.post("/liveness/check", response_model=LivenessResponse)
async def check_liveness(request: LivenessRequest):
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

    Every challenge_type is handled identically (single-image analysis) -
    see detect_blink's docstring for why "blink" specifically can't be
    genuinely implemented against a single image. challenge_type is
    accepted but otherwise unused.

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
    """
    if not base64_string:
        raise ValueError("Image data is empty")

    try:
        image_bytes = base64.b64decode(base64_string, validate=True)
        image = Image.open(BytesIO(image_bytes))
        image = image.convert("RGB")
    except Exception as exc:
        raise ValueError(f"Could not decode image: {exc}") from exc

    return np.array(image)


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
    """
    with mp.solutions.face_detection.FaceDetection(
        model_selection=0, min_detection_confidence=0.5
    ) as face_detector:
        results = face_detector.process(image_array)

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

    `detection` (from detect_face) is accepted for interface consistency
    with the rest of the pipeline (enroll_face/verify_face/check_liveness
    all call this the same way, and enroll_face's quality_score still
    needs MediaPipe's detection separately) but isn't used here -
    face_recognition.face_encodings() runs its own internal face
    detector rather than accepting a pre-computed bounding box. This
    means detection effectively runs twice (MediaPipe once, dlib once)
    per request, which is wasteful but deliberately kept simple and
    matches exactly what was empirically validated before switching -
    optimizing that away (e.g. by passing detection's bounding box in as
    known_face_locations) is a reasonable later improvement, not done
    here to avoid changing two things at once.

    Returns None if dlib's own detector can't find/encode a face (can
    happen even when MediaPipe's detect_face already succeeded, since
    they're different detectors and can disagree).
    """
    encodings = face_recognition.face_encodings(image_array)
    if not encodings:
        return None
    return encodings[0]


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
    the decoded image.
    """
    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, min_detection_confidence=0.5
    ) as face_mesh:
        results = face_mesh.process(image_array)

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


def detect_blink(face_mesh_landmarks):
    """
    Detect eye blink from face mesh landmarks (BONUS).

    TODO: Implement using:
    - Eye landmark indices (see MediaPipe docs)
    - Calculate Eye Aspect Ratio (EAR)
    - EAR < threshold indicates closed eye

    ---
    Not implemented. Genuine blink detection needs two states to compare
    (eye open, then closed) across separate frames/timestamps, but
    LivenessRequest.challenge_response is a single base64 image - there's
    no second frame to compare against, so an EAR-based blink check has
    nothing to detect a transition between. check_liveness below treats
    every challenge_type the same way (single-image/"passive" analysis)
    for this reason, rather than branching on "blink" specifically.
    """
    pass


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
    Implemented per the bullets above. Note docs/API-SPECIFICATION.md's
    own "Quick Start" sample code only checks 172.16-172.19 (a narrower,
    incomplete range) - this follows this docstring's explicit "172.16-31"
    instead, checking the second octet numerically rather than hardcoding
    16 string prefixes.
    """
    is_vpn = False
    confidence = 0.0

    if ip_address:
        if ip_address == "::1" or ip_address.startswith("127."):
            is_vpn = True
            confidence = 0.7
        elif ip_address.startswith("10.") or ip_address.startswith("192.168."):
            is_vpn = True
            confidence = 0.7
        else:
            octets = ip_address.split(".")
            if len(octets) == 4 and octets[0] == "172":
                try:
                    if 16 <= int(octets[1]) <= 31:
                        is_vpn = True
                        confidence = 0.7
                except ValueError:
                    pass

    if user_agent:
        vpn_keywords = ("vpn", "proxy", "tunnel", "tor")
        if any(keyword in user_agent.lower() for keyword in vpn_keywords):
            is_vpn = True
            confidence = max(confidence, 0.8)

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
