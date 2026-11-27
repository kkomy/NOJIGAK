"""Validated request/response contracts for stateless travel coaching."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

PredictionSource = Literal["api", "manual"]
TravelStrategy = Literal["efficient", "balanced", "safe"]
PredictionMethod = Literal["cold_start", "ewma_buffer", "empirical_quantile"]


class TravelRecord(BaseModel):
    """A completed trip with derived durations computed by the server."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    route_key: str = Field(min_length=1, max_length=160)
    target_arrival_at: datetime
    recommended_departure_at: datetime | None = None
    actual_departure_at: datetime
    actual_arrival_at: datetime
    api_travel_minutes: float | None = Field(default=None, gt=0, le=1440)
    predicted_travel_minutes: float | None = Field(default=None, gt=0, le=1440)
    effective_travel_minutes: float | None = Field(default=None, gt=0, le=1440)
    prediction_source: PredictionSource
    strategy: TravelStrategy = "balanced"
    abnormal: bool = False
    is_demo: bool = False
    has_intermediate_stop: bool = False

    @field_validator("id", "run_id", "route_key")
    @classmethod
    def identifiers_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("identifiers must not be blank")
        return normalized

    @field_validator(
        "target_arrival_at", "recommended_departure_at", "actual_departure_at", "actual_arrival_at"
    )
    @classmethod
    def require_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("datetime values must include a timezone")
        return value

    @field_validator("api_travel_minutes", "predicted_travel_minutes", "effective_travel_minutes")
    @classmethod
    def require_finite_minutes(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("travel minutes must be finite")
        return value

    @model_validator(mode="after")
    def validate_trip(self) -> "TravelRecord":
        if self.actual_arrival_at <= self.actual_departure_at:
            raise ValueError("actual_arrival_at must be after actual_departure_at")
        return self

    @computed_field
    @property
    def actual_travel_minutes(self) -> float:
        return (self.actual_arrival_at - self.actual_departure_at).total_seconds() / 60

    @computed_field
    @property
    def arrival_deviation_minutes(self) -> float:
        return (self.actual_arrival_at - self.target_arrival_at).total_seconds() / 60

    @computed_field
    @property
    def early_minutes(self) -> float:
        return max(0.0, -self.arrival_deviation_minutes)

    @computed_field
    @property
    def late_minutes(self) -> float:
        return max(0.0, self.arrival_deviation_minutes)


class TravelPredictRequest(BaseModel):
    route_key: str = Field(min_length=1, max_length=160)
    base_travel_minutes: float = Field(gt=0, le=1440)
    prediction_source: PredictionSource = "api"
    strategy: TravelStrategy = "balanced"
    history: list[TravelRecord] = Field(default_factory=list, max_length=500)

    @field_validator("route_key")
    @classmethod
    def predict_route_key_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("route_key must not be blank")
        return normalized

    @field_validator("base_travel_minutes")
    @classmethod
    def base_must_be_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("base_travel_minutes must be finite")
        return value


class StrategyEstimate(BaseModel):
    strategy: TravelStrategy
    target_quantile: float
    effective_travel_minutes: float
    strategy_margin_minutes: float
    method: PredictionMethod


class TravelPredictResponse(BaseModel):
    route_key: str
    api_travel_minutes: float | None
    point_estimate_minutes: float
    personal_correction_minutes: float
    strategy_margin_minutes: float
    effective_travel_minutes: float
    sample_count: int
    strategy: TravelStrategy
    target_quantile: float
    method: PredictionMethod
    prediction_source: PredictionSource
    strategy_comparison: dict[TravelStrategy, StrategyEstimate]


class TravelPlanRequest(TravelPredictRequest):
    target_arrival_at: datetime
    routine_minutes: float = Field(ge=0, le=1440)
    transition_minutes: float = Field(default=0, ge=0, le=1440)
    reserve_minutes: float = Field(default=0, ge=0, le=1440)
    arrival_buffer_minutes: float = Field(default=0, ge=0, le=1440)
    extra_travel_buffer_minutes: float = Field(default=0, ge=0, le=1440)
    previous_recommended_departure_at: datetime | None = None

    @field_validator(
        "target_arrival_at", "previous_recommended_departure_at"
    )
    @classmethod
    def plan_datetimes_are_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("datetime values must include a timezone")
        return value

    @field_validator("routine_minutes", "transition_minutes", "reserve_minutes", "arrival_buffer_minutes", "extra_travel_buffer_minutes")
    @classmethod
    def plan_minutes_are_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("plan time values must be finite")
        return value


class TravelPlanResponse(BaseModel):
    route_key: str
    strategy: TravelStrategy
    prediction: TravelPredictResponse
    target_arrival_at: datetime
    recommended_departure_at: datetime
    recommended_preparation_start_at: datetime
    movement_components: dict[str, float | None]
    previous_departure_at: datetime | None
    updated_departure_at: datetime
    # Signed as updated - previous: negative is earlier, positive is later.
    departure_shift_minutes: float | None
    departure_shift_direction: Literal["earlier", "later", "unchanged"] | None


class TravelMetricsRequest(BaseModel):
    records: list[TravelRecord] = Field(default_factory=list, max_length=500)
    route_key: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("route_key")
    @classmethod
    def metrics_route_key_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("route_key must not be blank")
        return normalized


class TravelMetricsResponse(BaseModel):
    route_key: str | None
    valid_record_count: int
    on_time_rate: float | None
    on_time_sample_count: int
    average_early_minutes: float | None
    early_sample_count: int
    average_late_minutes: float | None
    late_sample_count: int
    arrival_mae_minutes: float | None
    arrival_mae_sample_count: int
    departure_adherence_rate: float | None
    departure_adherence_sample_count: int
    api_travel_mae_minutes: float | None
    api_travel_mae_sample_count: int
    personal_travel_mae_minutes: float | None
    personal_travel_mae_sample_count: int


class TravelCompleteResponse(BaseModel):
    record: TravelRecord
    learning_eligible: bool
    actual_travel_minutes: float
    early_minutes: float
    late_minutes: float
