"""Pure, stateless travel-time learning and departure calculations."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite
from typing import Iterable, Literal

import numpy as np
from pydantic import ValidationError

from .travel_schemas import (
    StrategyEstimate,
    TravelMetricsResponse,
    TravelPlanRequest,
    TravelPlanResponse,
    TravelPredictRequest,
    TravelPredictResponse,
    TravelRecord,
)

ALPHA = 0.25
COLD_START_K = 8
MAX_RESIDUAL_HISTORY = 60
STRATEGIES: dict[str, dict[str, float | int | str]] = {
    "efficient": {"name": "시간 절약", "quantile": 0.60, "cold_start_buffer": 5, "min_samples": 10},
    "balanced": {"name": "균형", "quantile": 0.80, "cold_start_buffer": 10, "min_samples": 10},
    "safe": {"name": "안전 우선", "quantile": 0.95, "cold_start_buffer": 20, "min_samples": 40},
}


def route_group_key(
    origin: tuple[float, float],
    destination: tuple[float, float],
    route_signature: str | None = None,
) -> str:
    """Hash endpoint coordinates rounded to ~100m plus optional ODsay mapObj.

    Tuples use (longitude, latitude). The hash avoids returning raw coordinates.
    A mapObj is a route geometry signature, not claimed as a provider route ID.
    """
    coordinates = [*origin, *destination]
    if not all(isfinite(value) for value in coordinates):
        raise ValueError("route coordinates must be finite")
    if not (-180 <= origin[0] <= 180 and -90 <= origin[1] <= 90):
        raise ValueError("origin coordinates are out of range")
    if not (-180 <= destination[0] <= 180 and -90 <= destination[1] <= 90):
        raise ValueError("destination coordinates are out of range")
    parts = [f"{value:.3f}" for value in coordinates]
    canonical = "|".join(["public-transit-v1", *parts, (route_signature or "").strip()])
    return f"coord-v1:{sha256(canonical.encode('utf-8')).hexdigest()[:32]}"


def compute_ewma(values: Iterable[float], alpha: float = ALPHA) -> float | None:
    """Compute an ordered EWMA; residuals may be either positive or negative."""
    if not isfinite(alpha) or not 0 < alpha <= 1:
        raise ValueError("alpha must be finite and in (0, 1]")
    sequence = list(values)
    if not sequence:
        return None
    if any(not isfinite(value) for value in sequence):
        raise ValueError("EWMA values must be finite")
    result = float(sequence[0])
    for value in sequence[1:]:
        result = alpha * float(value) + (1 - alpha) * result
    return result


def validate_travel_record(record: TravelRecord | dict) -> TravelRecord:
    """Normalize a record through its schema; client-sent derived fields are ignored."""
    return record if isinstance(record, TravelRecord) else TravelRecord.model_validate(record)


def compute_travel_record(record: TravelRecord | dict) -> TravelRecord:
    """Return the schema-normalized record; all duration metrics derive from timestamps."""
    return validate_travel_record(record)


def is_learning_eligible(record: TravelRecord, demo_context: bool = False) -> bool:
    return (
        not record.abnormal
        and (demo_context or not record.is_demo)
        and not record.has_intermediate_stop
        and record.prediction_source == "api"
        and record.api_travel_minutes is not None
        and record.api_travel_minutes > 0
        and record.actual_travel_minutes > 0
        and isfinite(record.actual_travel_minutes)
    )


def filter_valid_records(
    records: Iterable[TravelRecord | dict],
    route_key: str | None = None,
    limit: int = MAX_RESIDUAL_HISTORY,
    demo_context: bool = False,
) -> list[TravelRecord]:
    """Filter API-predicted records and de-duplicate both ID and run_id."""
    valid: list[TravelRecord] = []
    for raw in records:
        try:
            record = validate_travel_record(raw)
        except (ValidationError, TypeError, ValueError):
            continue
        if route_key is not None and record.route_key != route_key:
            continue
        if is_learning_eligible(record, demo_context=demo_context):
            valid.append(record)

    valid.sort(key=lambda item: (item.actual_departure_at, item.id, item.run_id))
    unique: list[TravelRecord] = []
    seen_ids: set[str] = set()
    seen_runs: set[str] = set()
    for record in valid:
        if record.id in seen_ids or record.run_id in seen_runs:
            continue
        seen_ids.add(record.id)
        seen_runs.add(record.run_id)
        unique.append(record)
    return unique[-max(0, limit):] if limit else []


def _ordered_residuals(
    records: Iterable[TravelRecord | dict], route_key: str, demo_context: bool = False
) -> list[float]:
    selected = filter_valid_records(records, route_key, MAX_RESIDUAL_HISTORY, demo_context)
    return [record.actual_travel_minutes - float(record.api_travel_minutes) for record in selected]


def _strategy_method(sample_count: int, prediction_source: str, min_samples: int) -> Literal[
    "cold_start", "ewma_buffer", "empirical_quantile"
]:
    if prediction_source == "manual":
        return "cold_start"
    if sample_count >= min_samples:
        return "empirical_quantile"
    return "ewma_buffer" if sample_count else "cold_start"


def predict_travel_duration(
    route_key: str,
    base_travel_minutes: float,
    prediction_source: Literal["api", "manual"],
    strategy: Literal["efficient", "balanced", "safe"] = "balanced",
    history: Iterable[TravelRecord | dict] = (),
    demo_context: bool = False,
) -> TravelPredictResponse:
    """Blend route residual EWMA with a strategy quantile or cold-start margin."""
    if not isfinite(base_travel_minutes) or base_travel_minutes <= 0:
        raise ValueError("base_travel_minutes must be finite and positive")
    if strategy not in STRATEGIES:
        raise ValueError("unsupported travel strategy")

    residuals = _ordered_residuals(history, route_key, demo_context) if prediction_source == "api" else []
    sample_count = len(residuals)
    ewma = compute_ewma(residuals)
    weight = sample_count / (sample_count + COLD_START_K) if sample_count else 0.0
    correction = weight * (ewma or 0.0) if prediction_source == "api" else 0.0
    point_estimate = max(1.0, base_travel_minutes + correction)
    api_minutes = base_travel_minutes if prediction_source == "api" else None

    comparison: dict[str, StrategyEstimate] = {}
    previous_effective = 0.0
    current_result: StrategyEstimate | None = None
    for name, config in STRATEGIES.items():
        quantile = float(config["quantile"])
        minimum = int(config["min_samples"])
        method = _strategy_method(sample_count, prediction_source, minimum)
        if method == "empirical_quantile":
            quantile_residual = float(np.quantile(residuals, quantile, method="linear"))
            quantile_estimate = base_travel_minutes + weight * quantile_residual
            candidate = max(1.0, point_estimate, quantile_estimate)
        else:
            buffer = float(config["cold_start_buffer"])
            candidate = max(1.0, point_estimate, point_estimate + buffer)

        # Enforce a monotonic risk ordering even when a strategy lacks its
        # higher sample threshold or quantile noise would reverse the choices.
        effective = max(previous_effective, candidate)
        previous_effective = effective
        estimate = StrategyEstimate(
            strategy=name, target_quantile=quantile,
            effective_travel_minutes=effective,
            strategy_margin_minutes=effective - point_estimate,
            method=method,
        )
        comparison[name] = estimate
        if name == strategy:
            current_result = estimate

    assert current_result is not None
    return TravelPredictResponse(
        route_key=route_key,
        api_travel_minutes=api_minutes,
        point_estimate_minutes=point_estimate,
        personal_correction_minutes=correction,
        strategy_margin_minutes=current_result.strategy_margin_minutes,
        effective_travel_minutes=current_result.effective_travel_minutes,
        sample_count=sample_count,
        strategy=strategy,
        target_quantile=current_result.target_quantile,
        method=current_result.method,
        prediction_source=prediction_source,
        strategy_comparison=comparison,
    )


def recommend_departure(
    request: TravelPlanRequest,
    prediction: TravelPredictResponse | None = None,
) -> TravelPlanResponse:
    prediction = prediction or predict_travel_duration(
        request.route_key, request.base_travel_minutes, request.prediction_source,
        request.strategy, request.history, request.demo_context,
    )
    # The strategy margin is already part of effective_travel_minutes. Only
    # separately selected arrival and travel buffers are subtracted here.
    departure = request.target_arrival_at - timedelta(minutes=(
        prediction.effective_travel_minutes
        + request.arrival_buffer_minutes
        + request.extra_travel_buffer_minutes
    ))
    prep_start = departure - timedelta(minutes=(
        request.routine_minutes + request.transition_minutes + request.reserve_minutes
    ))
    previous = request.previous_recommended_departure_at
    shift = (departure - previous).total_seconds() / 60 if previous else None
    direction = None if shift is None else "earlier" if shift < -1e-9 else "later" if shift > 1e-9 else "unchanged"
    return TravelPlanResponse(
        route_key=request.route_key,
        strategy=request.strategy,
        prediction=prediction,
        target_arrival_at=request.target_arrival_at,
        recommended_departure_at=departure,
        recommended_preparation_start_at=prep_start,
        movement_components={
            "api_travel_minutes": prediction.api_travel_minutes,
            "point_estimate_minutes": prediction.point_estimate_minutes,
            "personal_correction_minutes": prediction.personal_correction_minutes,
            "strategy_margin_minutes": prediction.strategy_margin_minutes,
            "arrival_buffer_minutes": request.arrival_buffer_minutes,
            "extra_travel_buffer_minutes": request.extra_travel_buffer_minutes,
        },
        previous_departure_at=previous,
        updated_departure_at=departure,
        departure_shift_minutes=shift,
        departure_shift_direction=direction,
    )


def calculate_arrival_metrics(
    records: Iterable[TravelRecord | dict], route_key: str | None = None
) -> TravelMetricsResponse:
    """Compute outcome metrics; return null for any statistic without a sample."""
    valid: list[TravelRecord] = []
    seen_ids: set[str] = set()
    seen_runs: set[str] = set()
    normalized: list[TravelRecord] = []
    for raw in records:
        try:
            record = validate_travel_record(raw)
        except (ValidationError, TypeError, ValueError):
            continue
        if route_key and record.route_key != route_key:
            continue
        normalized.append(record)
    normalized.sort(key=lambda item: (item.actual_departure_at, item.id, item.run_id))
    for record in normalized:
        if record.abnormal or record.is_demo or record.id in seen_ids or record.run_id in seen_runs:
            continue
        seen_ids.add(record.id)
        seen_runs.add(record.run_id)
        valid.append(record)

    on_time = [item for item in valid if item.arrival_deviation_minutes <= 0]
    late = [item for item in valid if item.arrival_deviation_minutes > 0]
    adherent = [item for item in valid if item.recommended_departure_at is not None]
    travel_compare = [
        item for item in valid
        if not item.has_intermediate_stop
        and item.api_travel_minutes is not None
        and item.predicted_travel_minutes is not None
    ]

    def mean(values: list[float]) -> float | None:
        return float(np.mean(values)) if values else None

    arrival_errors = [abs(item.arrival_deviation_minutes) for item in valid]
    api_errors = [abs(item.actual_travel_minutes - float(item.api_travel_minutes)) for item in travel_compare]
    personal_errors = [abs(item.actual_travel_minutes - float(item.predicted_travel_minutes)) for item in travel_compare]
    return TravelMetricsResponse(
        route_key=route_key,
        valid_record_count=len(valid),
        on_time_rate=(len(on_time) / len(valid)) if valid else None,
        on_time_sample_count=len(valid),
        average_early_minutes=mean([item.early_minutes for item in on_time]),
        early_sample_count=len(on_time),
        average_late_minutes=mean([item.late_minutes for item in late]),
        late_sample_count=len(late),
        arrival_mae_minutes=mean(arrival_errors),
        arrival_mae_sample_count=len(arrival_errors),
        departure_adherence_rate=(
            sum(item.actual_departure_at <= item.recommended_departure_at for item in adherent) / len(adherent)
            if adherent else None
        ),
        departure_adherence_sample_count=len(adherent),
        api_travel_mae_minutes=mean(api_errors),
        api_travel_mae_sample_count=len(api_errors),
        personal_travel_mae_minutes=mean(personal_errors),
        personal_travel_mae_sample_count=len(personal_errors),
    )


