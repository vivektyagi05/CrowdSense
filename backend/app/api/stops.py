"""Stop endpoints: search/list, detail and scheduled departures."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db, get_db_v2
from app.errors import AppError
from app.schemas import SmartSearchResponse, ClusterResponse, DeparturesResponse, NearbyResponse, StopDetail, StopSearchResponse
from app.services import cluster_service, nearby_service, search_service
from app.services.stops_service import get_departures, get_stop, search_stops
from app.services.time_service import feed_today

router = APIRouter(tags=["stops"])


def _parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    if raw is None:
        return None
    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in raw.split(","))
    except ValueError:
        raise AppError(422, "validation_error", "bbox must be 'min_lon,min_lat,max_lon,max_lat' (four numbers).") from None
    if not (-180 <= min_lon <= max_lon <= 180 and -90 <= min_lat <= max_lat <= 90):
        raise AppError(422, "validation_error", "bbox must satisfy min <= max within [-180,180] x [-90,90].")
    return min_lon, min_lat, max_lon, max_lat


@router.get("/stops", response_model=SmartSearchResponse | StopSearchResponse, summary="Search or list bus stops (paginated); mode=smart adds ranked, typo-tolerant, cluster-grouped search")
def stops(
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    q: Annotated[str | None, Query(min_length=2, max_length=100, description="Part of a stop name")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    bbox: Annotated[str | None, Query(max_length=100, description="min_lon,min_lat,max_lon,max_lat")] = None,
    route_id: Annotated[str | None, Query(min_length=1, max_length=255, description="Only stops served by this route")] = None,
    mode: Annotated[Literal["substring", "smart"], Query(description="'smart' (Phase 4): normalised, typo-tolerant, ranked and grouped by place cluster; takes only q and limit")] = "substring",
) -> SmartSearchResponse | StopSearchResponse:
    if mode == "smart":
        if q is None:
            raise AppError(422, "validation_error", "mode=smart requires q.")
        if offset or bbox is not None or route_id is not None:
            raise AppError(422, "validation_error", "mode=smart accepts only q and limit.")
        return SmartSearchResponse(**search_service.smart_search(conn, q, limit))
    term = q.strip() if q is not None else None
    if q is not None and len(term or "") < 2:
        raise AppError(422, "validation_error", "q must contain at least 2 non-blank characters.")
    return search_stops(conn, term, limit, offset=offset, bbox=_parse_bbox(bbox), route_id=route_id)


@router.get("/stops/nearby", response_model=NearbyResponse, summary="Stops near a point, nearest first (real distances)")
def stops_nearby(
    conn: Annotated[sqlite3.Connection, Depends(get_db_v2)],
    lat: Annotated[float, Query(description="Latitude (WGS84). Never logged or stored by the server.")],
    lon: Annotated[float, Query(description="Longitude (WGS84). Never logged or stored by the server.")],
    radius_m: Annotated[int, Query(ge=nearby_service.RADIUS_MIN, le=nearby_service.RADIUS_MAX)] = nearby_service.RADIUS_DEFAULT,
    limit: Annotated[int, Query(ge=nearby_service.LIMIT_MIN, le=nearby_service.LIMIT_MAX)] = nearby_service.LIMIT_DEFAULT,
) -> NearbyResponse:
    nearby_service.validate_point(lat, lon)
    return NearbyResponse(**nearby_service.nearby_stops(conn, lat, lon, radius_m, limit))


@router.get("/stops/{stop_id}", response_model=StopDetail, response_model_exclude_none=False, summary="Stop details and serving routes")
def stop_detail(conn: Annotated[sqlite3.Connection, Depends(get_db_v2)], stop_id: str) -> StopDetail:
    return get_stop(conn, stop_id)


@router.get("/stops/{stop_id}/departures", response_model=DeparturesResponse, summary="Next scheduled departures from a stop")
def stop_departures(
    conn: Annotated[sqlite3.Connection, Depends(get_db_v2)],
    stop_id: str,
    date_: Annotated[date | None, Query(alias="date", description="Local service date YYYY-MM-DD (default: today in the feed's timezone)")] = None,
    after: Annotated[time | None, Query(description="Earliest local time HH:MM[:SS] (default 00:00:00)")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DeparturesResponse:
    service_date = date_ or feed_today(conn)
    seconds = 0 if after is None else after.hour * 3600 + after.minute * 60 + after.second
    return get_departures(conn, stop_id, service_date, seconds, limit)


@router.get("/clusters/{cluster_id}", response_model=ClusterResponse, tags=["clusters"],
            summary="A place cluster: the physical stops that share one name, with real distinguishing data")
def cluster_detail(conn: Annotated[sqlite3.Connection, Depends(get_db_v2)], cluster_id: str) -> ClusterResponse:
    return ClusterResponse(**cluster_service.get_cluster(conn, cluster_id))
