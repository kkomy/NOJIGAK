from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main

UTC = timezone.utc
TARGET = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)


def travel_record(ident: str = "trip-1", run_id: str = "run-1", *, actual: int = 88, api: int | None = 70):
    departed = TARGET - timedelta(minutes=95)
    arrived = departed + timedelta(minutes=actual)
    return {
        "id": ident,
        "run_id": run_id,
        "route_key": "route-a",
        "target_arrival_at": TARGET.isoformat(),
        "recommended_departure_at": (TARGET - timedelta(minutes=90)).isoformat(),
        "actual_departure_at": departed.isoformat(),
        "actual_arrival_at": arrived.isoformat(),
        "api_travel_minutes": api,
        "predicted_travel_minutes": 72,
        "effective_travel_minutes": 82,
        "prediction_source": "api" if api is not None else "manual",
        "strategy": "balanced",
        "abnormal": False,
        "is_demo": False,
    }


class OdsayResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"result": {"path": [{
            "pathType": 3,
            "info": {"totalTime": 67, "payment": 1500, "mapObj": "2:2:237:238"},
            "subPath": [
                {"trafficType": 3}, {"trafficType": 1}, {"trafficType": 3},
                {"trafficType": 2}, {"trafficType": 3},
            ],
        }]}}


class KakaoResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"documents": [{
            "place_name": "서울역", "road_address_name": "서울 중구 세종대로",
            "address_name": "서울 중구", "x": "126.97", "y": "37.55",
        }]}


class MockAsyncClient:
    calls: list[tuple[str, dict]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, params=None, **kwargs):
        self.calls.append((url, params or {}))
        if "dapi.kakao.com" in url and "keyword.json" in url:
            return KakaoResponse()
        return OdsayResponse()


class TravelApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_existing_health_and_personalize_contracts_remain(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})
        response = self.client.post("/api/personalize", json={"base_minutes": 10})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["predicted_minutes"], 10)
        openapi = self.client.get("/openapi.json").json()
        for path in ("/api/travel/predict", "/api/travel/plan", "/api/travel/complete", "/api/travel/metrics"):
            self.assertIn(path, openapi["paths"])

    def test_existing_places_contract_remains(self):
        with patch.dict(os.environ, {"KAKAO_REST_API_KEY": "test"}), patch.object(main.httpx, "AsyncClient", MockAsyncClient):
            response = self.client.get("/api/places", params={"q": "서울역"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["results"][0]["name"], "서울역")

    def test_route_string_and_coordinate_compatibility_and_route_metadata(self):
        MockAsyncClient.calls = []
        geocoded: list[str] = []

        async def fake_geocode(client, query, key):
            geocoded.append(query)
            return (127.1, 37.5) if query == "기존 출발지" else (127.2, 37.6)

        with patch.dict(os.environ, {"KAKAO_REST_API_KEY": "test", "ODSAY_API_KEY": "test"}), \
                patch.object(main.httpx, "AsyncClient", MockAsyncClient), \
                patch.object(main, "geocode", fake_geocode):
            coordinate = self.client.post("/api/route", json={
                "origin": "현재 위치", "origin_lat": 37.55, "origin_lng": 126.97,
                "destination": "목적지",
            })
            self.assertEqual(coordinate.status_code, 200, coordinate.text)
            data = coordinate.json()
            self.assertEqual(data["duration_minutes"], 67)
            self.assertEqual(data["transfers"], 1)
            self.assertFalse(data["realtime"])
            self.assertTrue(data["route_key"].startswith("coord-v1:"))
            self.assertEqual(data["route_signature"], "2:2:237:238")
            self.assertEqual(data["route_identity_source"], "odsay_map_object")
            self.assertEqual(geocoded, ["목적지"])
            odsay_params = MockAsyncClient.calls[-1][1]
            self.assertEqual(odsay_params["SX"], 126.97)
            self.assertEqual(odsay_params["SY"], 37.55)

            string = self.client.post("/api/route", json={"origin": "기존 출발지", "destination": "목적지"})
            self.assertEqual(string.status_code, 200, string.text)
            self.assertEqual(geocoded[-2:], ["목적지", "기존 출발지"])

    def test_invalid_route_coordinates_return_422_and_missing_keys_keep_503(self):
        invalid_pair = self.client.post("/api/route", json={
            "origin": "x", "destination": "y", "origin_lat": 37,
        })
        invalid_range = self.client.post("/api/route", json={
            "origin": "x", "destination": "y", "origin_lat": 91, "origin_lng": 0,
        })
        self.assertEqual(invalid_pair.status_code, 422)
        self.assertEqual(invalid_range.status_code, 422)
        with patch.dict(os.environ, {"KAKAO_REST_API_KEY": "", "ODSAY_API_KEY": ""}):
            self.assertEqual(self.client.post("/api/route", json={"origin": "x", "destination": "y"}).status_code, 503)

    def test_predict_cold_start_and_personalized_history(self):
        cold = self.client.post("/api/travel/predict", json={
            "route_key": "route-a", "base_travel_minutes": 70,
            "prediction_source": "api", "strategy": "balanced", "history": [],
        })
        self.assertEqual(cold.status_code, 200, cold.text)
        self.assertEqual(cold.json()["effective_travel_minutes"], 80)
        history = [travel_record()]
        learned = self.client.post("/api/travel/predict", json={
            "route_key": "route-a", "base_travel_minutes": 70,
            "prediction_source": "api", "strategy": "balanced", "history": history,
        })
        self.assertEqual(learned.status_code, 200, learned.text)
        self.assertEqual(learned.json()["point_estimate_minutes"], 72)
        self.assertEqual(learned.json()["sample_count"], 1)

    def test_plan_demo_context_is_explicit_and_preserves_default_demo_exclusion(self):
        fixture = travel_record("demo-trip", "demo-run")
        fixture["is_demo"] = True
        payload = {
            "route_key": "route-a", "base_travel_minutes": 70,
            "prediction_source": "api", "strategy": "balanced", "history": [fixture],
            "target_arrival_at": "2026-11-27T12:00:00+00:00", "routine_minutes": 60,
            "reserve_minutes": 5, "arrival_buffer_minutes": 4,
        }
        ordinary = self.client.post("/api/travel/plan", json=payload)
        demo = self.client.post("/api/travel/plan", json={**payload, "demo_context": True})
        self.assertEqual(ordinary.status_code, 200, ordinary.text)
        self.assertEqual(demo.status_code, 200, demo.text)
        self.assertEqual(ordinary.json()["prediction"]["sample_count"], 0)
        self.assertEqual(demo.json()["prediction"]["sample_count"], 1)

    def test_plan_completes_integrated_timeline_and_shift_sign(self):
        response = self.client.post("/api/travel/plan", json={
            "route_key": "route-a", "base_travel_minutes": 70,
            "prediction_source": "api", "strategy": "balanced", "history": [],
            "target_arrival_at": TARGET.isoformat(), "routine_minutes": 65,
            "transition_minutes": 4, "reserve_minutes": 5,
            "arrival_buffer_minutes": 5, "extra_travel_buffer_minutes": 3,
            "previous_recommended_departure_at": (TARGET - timedelta(minutes=80)).isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["departure_shift_minutes"], -8)
        self.assertEqual(data["departure_shift_direction"], "earlier")
        self.assertEqual(data["movement_components"]["strategy_margin_minutes"], 10)
        self.assertEqual(datetime.fromisoformat(data["recommended_preparation_start_at"].replace("Z", "+00:00")), TARGET - timedelta(minutes=162))

    def test_complete_recomputes_client_derived_metrics_and_learning_eligibility(self):
        body = travel_record(actual=88)
        body["actual_travel_minutes"] = 999
        body["arrival_deviation_minutes"] = -999
        response = self.client.post("/api/travel/complete", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["actual_travel_minutes"], 88)
        self.assertEqual(data["record"]["arrival_deviation_minutes"], -7)
        self.assertEqual(data["early_minutes"], 7)
        self.assertTrue(data["learning_eligible"])
        body["is_demo"] = True
        demo = self.client.post("/api/travel/complete", json=body)
        self.assertFalse(demo.json()["learning_eligible"])

    def test_metrics_empty_and_shared_mae_sample(self):
        empty = self.client.post("/api/travel/metrics", json={"records": []})
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertIsNone(empty.json()["on_time_rate"])
        self.assertEqual(empty.json()["api_travel_mae_sample_count"], 0)
        body = {"records": [
            travel_record("a", "r1", actual=80, api=70),
            travel_record("b", "r2", actual=100, api=90),
            travel_record("c", "r3", actual=100, api=90),
        ]}
        body["records"][0]["predicted_travel_minutes"] = 75
        body["records"][1]["predicted_travel_minutes"] = 95
        body["records"][2]["predicted_travel_minutes"] = None
        response = self.client.post("/api/travel/metrics", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["api_travel_mae_sample_count"], 2)
        self.assertEqual(data["personal_travel_mae_sample_count"], 2)
        self.assertEqual(data["api_travel_mae_minutes"], 10)
        self.assertEqual(data["personal_travel_mae_minutes"], 5)

    def test_invalid_nonfinite_or_naive_inputs_are_422(self):
        bad_minutes = self.client.post("/api/travel/predict", json={
            "route_key": "r", "base_travel_minutes": "NaN",
            "prediction_source": "api", "strategy": "balanced", "history": [],
        })
        naive_time = self.client.post("/api/travel/complete", json={
            **travel_record(), "actual_departure_at": "2026-11-27T08:00:00",
        })
        self.assertEqual(bad_minutes.status_code, 422)
        self.assertEqual(naive_time.status_code, 422)


if __name__ == "__main__":
    unittest.main()
