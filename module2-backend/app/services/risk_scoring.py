"""
Multi-signal risk scoring for check-ins (Task 2.7 / SECURITY-REQUIREMENTS.md).

Prefers Module 3's POST /risk/assess (the full 5-signal weighted formula -
see IMPLEMENTATION-PLAN.md's gotcha on this) when reachable, as the base
score. When it isn't (currently: always, since Module 3 is a 501 stub -
see KNOWN-ISSUES.md), falls back to compute_fallback_risk()'s local
approximation using only the signals Module 2 can see without Module 3:
liveness, geofence distance, device trust.

On top of whichever base score is used, `assess()` layers Module 2's own
discrete signals Module 3 has no way to know about (device_unknown/
untrusted from our own Device table, impossible_travel, GPS accuracy) as
risk_signals rows with additive score bumps, then applies the canonical
decision table + hard override from IMPLEMENTATION-PLAN.md's "Team
decisions" §1 Decision Synthesis. This is the single place check-in
status gets decided - routers/checkins.py should never re-derive it.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

# 0.3 and 0.7 are fixed system constants (only 0.7/CRITICAL is checked
# directly here - below it, the configurable risk_threshold decides
# approved vs flagged; 0.3 doesn't need its own branch since anything
# under the - always <= 0.5 - threshold is already "approved").
CRITICAL_THRESHOLD = 0.7

# Weights for the fallback formula, used only when Module 3 is
# unreachable. Full weights per SECURITY-REQUIREMENTS.md are Liveness 25%,
# Face Match 25%, Device 20%, Network 15%, Geolocation 15% - without
# Module 3 there's no face_match or network signal, so the remaining
# three are renormalized to still sum to 1.0 instead of silently assuming
# worst-case risk for whatever's missing.
_FALLBACK_WEIGHTS = {"liveness": 0.25, "device": 0.20, "geolocation": 0.15}
_FALLBACK_WEIGHT_SUM = sum(_FALLBACK_WEIGHTS.values())  # 0.60

# Additive bumps for discrete signals Module 3 can't see (our own Device
# table, impossible travel, GPS precision) - layered on top of whichever
# base score is used, final score capped at 1.0.
_GEO_OUT_OF_BOUNDS_WEIGHT = 0.15
_GEO_ACCURACY_LOW_WEIGHT = 0.05
_GEO_ACCURACY_LOW_METERS = 100.0  # accuracy worse than this = "low"
_DEVICE_UNKNOWN_WEIGHT = 0.10
_DEVICE_UNTRUSTED_WEIGHT = 0.05
_IMPOSSIBLE_TRAVEL_WEIGHT = 0.30
_IMPOSSIBLE_TRAVEL_KMH = 250.0  # faster than this between two check-ins = impossible
_LIVENESS_FAILED_WEIGHT = 0.25


@dataclass
class RiskSignal:
    signal_type: str
    severity: str
    weight: float
    confidence: float = 1.0
    details: Optional[dict[str, Any]] = None


@dataclass
class RiskAssessment:
    risk_score: float
    status: str  # approved | flagged | rejected
    signals: list[RiskSignal] = field(default_factory=list)

    @property
    def risk_factors(self) -> list[dict[str, Any]]:
        """Denormalized summary for checkins.risk_factors, matching
        API-SPECIFICATION.md's `[{"type": ..., "weight": ...}]` shape."""
        return [{"type": s.signal_type, "weight": s.weight} for s in self.signals]


def compute_fallback_risk(
    liveness_score: float, distance_ratio: Optional[float], device_trusted: Optional[bool]
) -> float:
    """Local approximation used only when Module 3's /risk/assess itself
    is unreachable. distance_ratio = distance_meters / geofence_radius, or
    None if no venue is configured (treated as no geo signal, not risky)."""
    liveness_component = 1.0 - liveness_score
    geo_component = 0.0 if distance_ratio is None else min(distance_ratio, 1.0)
    if device_trusted is None:
        device_component = 0.5  # unknown - uncertain, not assumed worst-case
    else:
        device_component = 0.0 if device_trusted else 0.6

    weighted = (
        liveness_component * _FALLBACK_WEIGHTS["liveness"]
        + device_component * _FALLBACK_WEIGHTS["device"]
        + geo_component * _FALLBACK_WEIGHTS["geolocation"]
    ) / _FALLBACK_WEIGHT_SUM
    return round(min(max(weighted, 0.0), 1.0), 4)


def assess(
    *,
    base_risk_score: float,
    distance_meters: Optional[float],
    geofence_radius: float,
    location_accuracy_meters: Optional[float],
    liveness_passed: Optional[bool],
    device_known: bool,
    device_trusted: Optional[bool],
    previous_checkin_at: Optional[datetime],
    previous_distance_meters: Optional[float],
    current_checkin_at: datetime,
    risk_threshold: float,
) -> RiskAssessment:
    signals: list[RiskSignal] = []
    hard_reject = False

    if distance_meters is not None and geofence_radius > 0 and distance_meters > geofence_radius:
        severity = "critical" if distance_meters > 2 * geofence_radius else "high"
        signals.append(RiskSignal(
            "geo_out_of_bounds", severity, weight=_GEO_OUT_OF_BOUNDS_WEIGHT,
            details={"distance_meters": round(distance_meters, 1), "geofence_radius_meters": geofence_radius},
        ))
        if distance_meters > 2 * geofence_radius:
            hard_reject = True

    if location_accuracy_meters is not None and location_accuracy_meters > _GEO_ACCURACY_LOW_METERS:
        signals.append(RiskSignal(
            "geo_accuracy_low", "low", weight=_GEO_ACCURACY_LOW_WEIGHT,
            details={"accuracy_meters": location_accuracy_meters},
        ))

    if not device_known:
        signals.append(RiskSignal("device_unknown", "medium", weight=_DEVICE_UNKNOWN_WEIGHT))
    elif device_trusted is False:
        signals.append(RiskSignal(
            "device_unknown", "low", weight=_DEVICE_UNTRUSTED_WEIGHT,
            details={"reason": "device registered but not marked trusted"},
        ))

    if previous_checkin_at is not None and previous_distance_meters is not None:
        elapsed_hours = max((current_checkin_at - previous_checkin_at).total_seconds() / 3600.0, 1e-6)
        implied_kmh = (previous_distance_meters / 1000.0) / elapsed_hours
        if implied_kmh > _IMPOSSIBLE_TRAVEL_KMH:
            signals.append(RiskSignal(
                "impossible_travel", "critical", weight=_IMPOSSIBLE_TRAVEL_WEIGHT,
                details={"implied_speed_kmh": round(implied_kmh, 1)},
            ))

    if liveness_passed is False:
        signals.append(RiskSignal("liveness_failed", "critical", weight=_LIVENESS_FAILED_WEIGHT))
        hard_reject = True

    score = base_risk_score + sum(s.weight for s in signals)
    score = round(min(max(score, 0.0), 1.0), 4)

    if hard_reject or score >= CRITICAL_THRESHOLD:
        status = "rejected"
    elif score >= risk_threshold:
        status = "flagged"
    else:
        status = "approved"

    return RiskAssessment(risk_score=score, status=status, signals=signals)
