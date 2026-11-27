from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from backend.app.travel import (
    calculate_arrival_metrics,
    compute_ewma,
    filter_valid_records,
    is_learning_eligible,
    predict_travel_duration,
    recommend_departure,
    route_group_key,
)
from backend.app.travel_schemas import TravelPlanRequest, TravelRecord

UTC = timezone.utc
BASE = datetime(2026, 11, 27, 0, 0, tzinfo=UTC)


def record(
    ident: str,
    run_id: str,
    *,
    route: str = "route-a",
    actual_minutes: float = 88,
    api_minutes: float | None = 70,
    source: str = "api",
    abnormal: bool = False,
    demo: bool = False,
    stop: bool = False,
    index: int = 0,
    predicted: float | None = 72,
    recommended: datetime | None = None,
) -> TravelRecord:
    departure = BASE + timedelta(days=index)
    arrival = departure + timedelta(minutes=actual_minutes)
    return TravelRecord(
        id=ident,
        run_id=run_id,
        route_key=route,
        target_arrival_at=arrival + timedelta(minutes=5),
        recommended_departure_at=recommended,
        actual_departure_at=departure,
        actual_arrival_at=arrival,
        api_travel_minutes=api_minutes,
        predicted_travel_minutes=predicted,
        effective_travel_minutes=80 if source == "api" else actual_minutes,
        prediction_source=source,
        abnormal=abnormal,
        is_demo=demo,
        has_intermediate_stop=stop,
    )


class TravelRecordTests(unittest.TestCase):
    def test_server_derives_trip_and_arrival_durations(self):
        item = record("a", "r1", actual_minutes=88)
        self.assertEqual(item.actual_travel_minutes, 88)
        self.assertEqual(item.arrival_deviation_minutes, -5)
        self.assertEqual(item.early_minutes, 5)
        self.assertEqual(item.late_minutes, 0)
        forged = TravelRecord.model_validate({**item.model_dump(), "actual_travel_minutes": 1, "arrival_deviation_minutes": 999})
        self.assertEqual(forged.actual_travel_minutes, 88)
        self.assertEqual(forged.arrival_deviation_minutes, -5)

    def test_naive_datetime_and_non_positive_trip_are_rejected(self):
        data = record("a", "r1").model_dump()
        data["target_arrival_at"] = datetime(2026, 1, 1)
        with self.assertRaises(ValidationError):
            TravelRecord.model_validate(data)
        data = record("a", "r1").model_dump()
        data["actual_arrival_at"] = data["actual_departure_at"]
        with self.assertRaises(ValidationError):
            TravelRecord.model_validate(data)
        data = record("b", "r2").model_dump()
        data["api_travel_minutes"] = float("nan")
        with self.assertRaises(ValidationError):
            TravelRecord.model_validate(data)

    def test_datetime_and_plan_arithmetic_cross_midnight(self):
        request = TravelPlanRequest(
            route_key="r", base_travel_minutes=70, prediction_source="api", strategy="balanced",
            target_arrival_at=datetime(2026, 1, 2, 0, 30, tzinfo=timezone(timedelta(hours=9))),
            routine_minutes=65, transition_minutes=0, reserve_minutes=5,
            arrival_buffer_minutes=5, extra_travel_buffer_minutes=0,
        )
        planned = recommend_departure(request)
        self.assertEqual(planned.recommended_departure_at, datetime(2026, 1, 1, 23, 5, tzinfo=timezone(timedelta(hours=9))))
        self.assertEqual(planned.recommended_preparation_start_at, planned.recommended_departure_at - timedelta(minutes=70))


class TravelLearningTests(unittest.TestCase):
    def test_demo_records_need_explicit_calculation_context(self):
        fixture = record("demo", "demo-run", demo=True)
        self.assertFalse(is_learning_eligible(fixture))
        self.assertEqual(filter_valid_records([fixture], "route-a"), [])
        self.assertEqual(filter_valid_records([fixture], "route-a", demo_context=True), [fixture])
        self.assertTrue(is_learning_eligible(fixture, demo_context=True))
        ordinary = predict_travel_duration("route-a", 70, "api", "balanced", [fixture])
        demo = predict_travel_duration("route-a", 70, "api", "balanced", [fixture], demo_context=True)
        self.assertEqual(ordinary.sample_count, 0)
        self.assertEqual(demo.sample_count, 1)

    def test_coordinate_group_key_is_normalized_hashed_and_signature_aware(self):
        first = route_group_key((127.0001, 37.5001), (126.9001, 37.6001), "map-a")
        same_group = route_group_key((127.0002, 37.5002), (126.9002, 37.6002), "map-a")
        other_geometry = route_group_key((127.0001, 37.5001), (126.9001, 37.6001), "map-b")
        self.assertEqual(first, same_group)
        self.assertNotEqual(first, other_geometry)
        self.assertNotIn("127.000", first)

    def test_cold_start_positive_and_negative_residual_examples(self):
        self.assertAlmostEqual(compute_ewma([]) or 0, 0)
        empty = predict_travel_duration("route-a", 70, "api", "balanced", [])
        self.assertEqual(empty.sample_count, 0)
        self.assertEqual(empty.personal_correction_minutes, 0)
        self.assertEqual(empty.effective_travel_minutes, 80)
        positive = predict_travel_duration("route-a", 70, "api", "balanced", [record("a", "r1")])
        self.assertEqual(positive.point_estimate_minutes, 72)
        negative = predict_travel_duration("route-a", 70, "api", "balanced", [record("b", "r2", actual_minutes=52)])
        self.assertEqual(negative.point_estimate_minutes, 68)

    def test_ewma_uses_departure_order_and_deduplicates_ids_and_runs(self):
        later = record("later", "run-later", actual_minutes=100, index=2)
        earlier = record("earlier", "run-earlier", actual_minutes=80, index=1)
        duplicate_id = record("earlier", "different-run", actual_minutes=120, index=3)
        duplicate_run = record("other-id", "run-earlier", actual_minutes=150, index=4)
        valid = filter_valid_records([later, earlier, duplicate_id, duplicate_run], "route-a")
        self.assertEqual([item.id for item in valid], ["earlier", "later"])
        prediction = predict_travel_duration("route-a", 70, "api", "balanced", [later, earlier])
        # residuals 10 then 30 => EWMA 15; n=2 gives 0.2 weight => +3.
        self.assertEqual(prediction.point_estimate_minutes, 73)
        self.assertEqual(prediction.sample_count, 2)

    def test_route_source_and_quality_filters(self):
        history = [
            record("a", "run-a", route="route-a"),
            record("b", "run-b", route="route-b", actual_minutes=200),
            record("c", "run-c", abnormal=True),
            record("d", "run-d", demo=True),
            record("e", "run-e", source="manual"),
            record("f", "run-f", stop=True),
        ]
        usable = filter_valid_records(history, "route-a")
        self.assertEqual([item.id for item in usable], ["a"])
        manual = predict_travel_duration("route-a", 70, "manual", "balanced", history)
        self.assertEqual(manual.point_estimate_minutes, 70)
        self.assertEqual(manual.personal_correction_minutes, 0)
        self.assertIsNone(manual.api_travel_minutes)

    def test_quantile_sample_thresholds_and_strategy_order(self):
        history = [record(str(i), f"run-{i}", actual_minutes=70 + (50 if i == 19 else i % 4), index=i) for i in range(39)]
        result = predict_travel_duration("route-a", 70, "api", "efficient", history)
        self.assertEqual(result.strategy_comparison["efficient"].method, "empirical_quantile")
        self.assertEqual(result.strategy_comparison["balanced"].method, "empirical_quantile")
        self.assertEqual(result.strategy_comparison["safe"].method, "ewma_buffer")
        values = [result.strategy_comparison[name].effective_travel_minutes for name in ("efficient", "balanced", "safe")]
        self.assertLessEqual(values[0], values[1])
        self.assertLessEqual(values[1], values[2])
        enough = predict_travel_duration("route-a", 70, "api", "safe", [record(str(i), f"s-{i}", index=i) for i in range(40)])
        self.assertEqual(enough.method, "empirical_quantile")

    def test_manual_input_does_not_reuse_api_residuals(self):
        history = [record("a", "r1", actual_minutes=120)]
        manual = predict_travel_duration("route-a", 60, "manual", "balanced", history)
        self.assertEqual(manual.point_estimate_minutes, 60)
        self.assertEqual(manual.effective_travel_minutes, 70)
        self.assertEqual(manual.sample_count, 0)


class TimelineAndMetricTests(unittest.TestCase):
    def test_strategy_margin_and_explicit_buffers_are_subtracted_once(self):
        target = BASE + timedelta(hours=3)
        request = TravelPlanRequest(
            route_key="route-a", base_travel_minutes=70, prediction_source="api", strategy="balanced",
            target_arrival_at=target, routine_minutes=65, transition_minutes=4,
            reserve_minutes=5, arrival_buffer_minutes=5, extra_travel_buffer_minutes=3,
        )
        plan = recommend_departure(request)
        # 70 API + 10 strategy margin + 5 arrival buffer + 3 explicit buffer.
        self.assertEqual((target - plan.recommended_departure_at).total_seconds() / 60, 88)
        self.assertEqual((plan.recommended_departure_at - plan.recommended_preparation_start_at).total_seconds() / 60, 74)

    def test_increased_travel_time_moves_departure_earlier_with_signed_shift(self):
        target = BASE + timedelta(hours=4)
        request = TravelPlanRequest(
            route_key="route-a", base_travel_minutes=70, prediction_source="api", strategy="balanced",
            target_arrival_at=target, routine_minutes=65,
            previous_recommended_departure_at=target - timedelta(minutes=70),
        )
        plan = recommend_departure(request)
        self.assertEqual(plan.departure_shift_minutes, -10)
        self.assertEqual(plan.departure_shift_direction, "earlier")

    def test_metrics_empty_and_same_sample_travel_mae(self):
        empty = calculate_arrival_metrics([])
        self.assertIsNone(empty.on_time_rate)
        self.assertIsNone(empty.api_travel_mae_minutes)
        items = [
            record("a", "r1", actual_minutes=80, api_minutes=70, predicted=75, index=0),
            record("b", "r2", actual_minutes=100, api_minutes=90, predicted=95, index=1),
            record("c", "r3", actual_minutes=100, api_minutes=90, predicted=None, index=2),
            record("demo", "r4", demo=True, index=3),
        ]
        metrics = calculate_arrival_metrics(items)
        self.assertEqual(metrics.valid_record_count, 3)
        self.assertEqual(metrics.api_travel_mae_sample_count, 2)
        self.assertEqual(metrics.personal_travel_mae_sample_count, 2)
        self.assertEqual(metrics.api_travel_mae_minutes, 10)
        self.assertEqual(metrics.personal_travel_mae_minutes, 5)

    def test_arrival_and_departure_stats_cover_late_and_adherent_runs(self):
        recommended = BASE
        early = record("early", "e1", actual_minutes=50, api_minutes=45, predicted=48, recommended=recommended, index=0)
        late = record("late", "l1", actual_minutes=60, api_minutes=55, predicted=58, recommended=recommended, index=1)
        late = late.model_copy(update={"target_arrival_at": late.actual_arrival_at - timedelta(minutes=5)})
        metrics = calculate_arrival_metrics([early, late])
        self.assertEqual(metrics.on_time_rate, 0.5)
        self.assertEqual(metrics.average_early_minutes, 5)
        self.assertEqual(metrics.average_late_minutes, 5)
        self.assertEqual(metrics.arrival_mae_minutes, 5)
        self.assertEqual(metrics.departure_adherence_rate, 0.5)


if __name__ == "__main__":
    unittest.main()
