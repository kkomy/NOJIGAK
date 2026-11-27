"""Small API-key-safe proxy for Kakao Local and ODsay route lookup."""
import os
from datetime import datetime, timezone
from typing import Any

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from .travel import calculate_arrival_metrics, compute_travel_record, predict_travel_duration, recommend_departure, route_group_key
from .travel_schemas import (
    TravelCompleteResponse,
    TravelMetricsRequest,
    TravelMetricsResponse,
    TravelPlanRequest,
    TravelPlanResponse,
    TravelPredictRequest,
    TravelPredictResponse,
    TravelRecord,
)

app = FastAPI(title="AI Departure Coach API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class RouteRequest(BaseModel):
    origin: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    origin_lat: float | None = None
    origin_lng: float | None = None

    @model_validator(mode="after")
    def validate_origin_coordinates(self) -> "RouteRequest":
        if (self.origin_lat is None) != (self.origin_lng is None):
            raise ValueError("origin_lat and origin_lng must be provided together")
        if self.origin_lat is not None and not (-90 <= self.origin_lat <= 90 and -180 <= self.origin_lng <= 180):
            raise ValueError("origin coordinates are out of range")
        return self


class PersonalizationRequest(BaseModel):
    base_minutes: int = Field(ge=1, le=600)
    valid_durations_minutes: list[float] = Field(default_factory=list, max_length=500)
    alpha: float = Field(default=0.25, gt=0, le=1)
    cold_start_k: int = Field(default=8, ge=1, le=100)
    quantile_threshold: int = Field(default=10, ge=2, le=100)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/personalize")
async def personalize(payload: PersonalizationRequest) -> dict[str, Any]:
    """Optional server-side mirror of the offline browser estimator."""
    values = np.asarray([v for v in payload.valid_durations_minutes if np.isfinite(v) and v > 0], dtype=float)
    if values.size == 0:
        return {"predicted_minutes": payload.base_minutes, "ewma_minutes": None, "sample_count": 0, "method": "cold_start"}
    ewma = float(values[0])
    for actual in values[1:]:
        ewma = payload.alpha * float(actual) + (1 - payload.alpha) * ewma
    individual = ewma
    method = "ewma"
    if values.size >= payload.quantile_threshold:
        q80 = float(np.quantile(values[-20:], 0.8, method="linear"))
        individual = max(ewma, q80)
        method = "ewma_q80"
    weight = values.size / (values.size + payload.cold_start_k)
    estimate = (1 - weight) * payload.base_minutes + weight * individual
    return {"predicted_minutes": int(np.ceil(estimate)), "ewma_minutes": round(ewma, 2), "individual_minutes": round(individual, 2), "sample_count": int(values.size), "method": method}


@app.get("/api/places")
async def places(q: str = Query(min_length=1, max_length=100)) -> dict[str, Any]:
    key = os.getenv("KAKAO_REST_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="Kakao Local API key is not configured")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            res = await client.get(
                "https://dapi.kakao.com/v2/local/search/keyword.json",
                params={"query": q, "size": 8},
                headers={"Authorization": f"KakaoAK {key}"},
            )
            res.raise_for_status()
            docs = res.json().get("documents", [])
            return {"results": [{"name": x.get("place_name", ""), "address": x.get("road_address_name") or x.get("address_name", ""), "x": x.get("x"), "y": x.get("y")} for x in docs]}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Kakao Local API lookup failed") from exc


async def geocode(client: httpx.AsyncClient, query: str, key: str) -> tuple[float, float]:
    response = await client.get(
        "https://dapi.kakao.com/v2/local/search/address.json",
        params={"query": query, "size": 1},
        headers={"Authorization": f"KakaoAK {key}"},
    )
    response.raise_for_status()
    docs = response.json().get("documents", [])
    if not docs:
        response = await client.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            params={"query": query, "size": 1},
            headers={"Authorization": f"KakaoAK {key}"},
        )
        response.raise_for_status()
        docs = response.json().get("documents", [])
    if not docs:
        raise HTTPException(status_code=404, detail=f"Could not locate: {query}")
    return float(docs[0]["x"]), float(docs[0]["y"])


@app.post("/api/route")
async def route(payload: RouteRequest) -> dict[str, Any]:
    kakao = os.getenv("KAKAO_REST_API_KEY")
    odsay = os.getenv("ODSAY_API_KEY")
    if not odsay or (payload.origin_lat is None and not kakao) or not kakao:
        raise HTTPException(status_code=503, detail="Route lookup keys are not configured")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            destination = await geocode(client, payload.destination, kakao)
            origin = (payload.origin_lng, payload.origin_lat) if payload.origin_lat is not None else await geocode(client, payload.origin, kakao)
            res = await client.get(
                "https://api.odsay.com/v1/api/searchPubTransPathT",
                params={"SX": origin[0], "SY": origin[1], "EX": destination[0], "EY": destination[1], "apiKey": odsay},
            )
            res.raise_for_status()
            body = res.json()
            paths = body.get("result", {}).get("path", [])
            if not paths:
                raise HTTPException(status_code=404, detail="No transit route found")
            path = paths[0]
            info = path.get("info", {})
            duration = info.get("totalTime")
            if not isinstance(duration, (int, float)) or not np.isfinite(duration) or duration <= 0:
                raise HTTPException(status_code=502, detail="Transit route returned an invalid duration")
            rides = [part for part in path.get("subPath", []) if part.get("trafficType") in (1, 2)]
            transfers = max(0, len(rides) - 1) if rides else None
            payment = info.get("payment")
            raw_signature = info.get("mapObj")
            route_signature = raw_signature.strip()[:256] if isinstance(raw_signature, str) and raw_signature.strip() else None
            route_key = route_group_key(origin, destination, route_signature)
            return {
                "duration_minutes": int(duration),
                "source": "ODsay 대중교통 경로",
                "transfers": transfers,
                "fare": payment if isinstance(payment, (int, float)) and payment > 0 else None,
                "realtime": False,
                "route_key": route_key,
                "route_signature": route_signature,
                "route_identity_source": "odsay_map_object" if route_signature else "endpoint_coordinate_group",
                "route_grouping": "endpoint_coordinates_0.001deg",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "prediction_source": "api",
            }
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Transit route lookup failed") from exc


@app.post("/api/travel/predict", response_model=TravelPredictResponse)
async def travel_predict(payload: TravelPredictRequest) -> TravelPredictResponse:
    return predict_travel_duration(
        route_key=payload.route_key,
        base_travel_minutes=payload.base_travel_minutes,
        prediction_source=payload.prediction_source,
        strategy=payload.strategy,
        history=payload.history,
        demo_context=payload.demo_context,
    )


@app.post("/api/travel/plan", response_model=TravelPlanResponse)
async def travel_plan(payload: TravelPlanRequest) -> TravelPlanResponse:
    return recommend_departure(payload)


@app.post("/api/travel/complete", response_model=TravelCompleteResponse)
async def travel_complete(payload: TravelRecord) -> TravelCompleteResponse:
    from .travel import is_learning_eligible

    record = compute_travel_record(payload)
    return TravelCompleteResponse(
        record=record,
        learning_eligible=is_learning_eligible(record),
        actual_travel_minutes=record.actual_travel_minutes,
        early_minutes=record.early_minutes,
        late_minutes=record.late_minutes,
    )


@app.post("/api/travel/metrics", response_model=TravelMetricsResponse)
async def travel_metrics(payload: TravelMetricsRequest) -> TravelMetricsResponse:
    return calculate_arrival_metrics(payload.records, payload.route_key)
