"""Reproducible, in-memory 수도권 통학 scenario. Run from repository root."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.travel import (
    calculate_arrival_metrics,
    is_learning_eligible,
    predict_travel_duration,
    recommend_departure,
)
from app.travel_schemas import TravelPlanRequest, TravelRecord

KST = ZoneInfo("Asia/Seoul")
ROUTE_KEY = "demo-gyeonggi-seoul-transit"
TARGET = datetime(2026, 11, 30, 9, 0, tzinfo=KST)


def main() -> None:
    # Synthetic records are isolated in this script; none are written to storage.
    residuals = [8, 12, 16, 10, 18, 14, 20]
    history = []
    for index, residual in enumerate(residuals):
        departure = datetime(2026, 11, 16 + index, 7, 15, tzinfo=KST)
        api_minutes = 70
        history.append(TravelRecord(
            id=f"fixture-{index}", run_id=f"fixture-run-{index}", route_key=ROUTE_KEY,
            target_arrival_at=departure + timedelta(minutes=api_minutes + residual + 5),
            recommended_departure_at=departure,
            actual_departure_at=departure,
            actual_arrival_at=departure + timedelta(minutes=api_minutes + residual),
            api_travel_minutes=api_minutes, predicted_travel_minutes=api_minutes,
            effective_travel_minutes=api_minutes, prediction_source="api", strategy="balanced",
        ))

    def make_plan(api_minutes: float, strategy: str, previous=None) -> TravelPlanRequest:
        return TravelPlanRequest(
            route_key=ROUTE_KEY,
            base_travel_minutes=api_minutes,
            prediction_source="api",
            strategy=strategy,
            history=history,
            target_arrival_at=TARGET,
            routine_minutes=65,
            transition_minutes=0,
            reserve_minutes=5,
            arrival_buffer_minutes=5,
            extra_travel_buffer_minutes=0,
            previous_recommended_departure_at=previous,
        )

    initial_strategies = {}
    for strategy in ("efficient", "balanced", "safe"):
        planned = recommend_departure(make_plan(70, strategy))
        initial_strategies[strategy] = {
            "effective_travel_minutes": planned.prediction.effective_travel_minutes,
            "recommended_departure_at": planned.recommended_departure_at.isoformat(),
            "recommended_preparation_start_at": planned.recommended_preparation_start_at.isoformat(),
        }

    before = recommend_departure(make_plan(70, "balanced"))
    updated = recommend_departure(make_plan(82, "balanced", before.recommended_departure_at))
    departure = updated.recommended_departure_at
    completion = TravelRecord(
        id="demo-trip", run_id="demo-run", route_key=ROUTE_KEY,
        target_arrival_at=TARGET,
        recommended_departure_at=departure,
        actual_departure_at=departure,
        actual_arrival_at=departure + timedelta(minutes=105),
        api_travel_minutes=82,
        predicted_travel_minutes=updated.prediction.point_estimate_minutes,
        effective_travel_minutes=updated.prediction.effective_travel_minutes,
        prediction_source="api", strategy="balanced", is_demo=True,
    )

    # The stored/returned fixture remains is_demo=True and is excluded from
    # real learning. A transient copy is permitted only in this demo's isolated
    # calculation context to show how a new actual trip changes the next plan.
    demo_only_record = completion.model_copy(update={"is_demo": False})
    demo_only_history = [*history, demo_only_record]
    next_prediction = predict_travel_duration(ROUTE_KEY, 82, "api", "balanced", demo_only_history)
    output = {
        "route_key": ROUTE_KEY,
        "history_count": len(history),
        "initial_api_travel_minutes": 70,
        "initial_strategy_recommendations": initial_strategies,
        "updated_api_travel_minutes": 82,
        "updated_point_estimate_minutes": updated.prediction.point_estimate_minutes,
        "updated_effective_travel_minutes": updated.prediction.effective_travel_minutes,
        "updated_recommended_departure_at": updated.recommended_departure_at.isoformat(),
        "departure_shift_minutes_updated_minus_previous": updated.departure_shift_minutes,
        "departure_shift_direction": updated.departure_shift_direction,
        "completion": {
            "actual_travel_minutes": completion.actual_travel_minutes,
            "arrival_deviation_minutes": completion.arrival_deviation_minutes,
            "early_minutes": completion.early_minutes,
            "late_minutes": completion.late_minutes,
            "learning_eligible_in_real_context": is_learning_eligible(completion),
        },
        "demo_scoped_next_prediction_after_actual_record": {
            "sample_count": next_prediction.sample_count,
            "point_estimate_minutes": next_prediction.point_estimate_minutes,
            "effective_travel_minutes": next_prediction.effective_travel_minutes,
        },
        "demo_metrics": calculate_arrival_metrics([demo_only_record]).model_dump(mode="json"),
        "persistence": "none; all records exist only in this process invocation",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
