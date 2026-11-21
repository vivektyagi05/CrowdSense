"""Agencies, routes, trips and shapes."""

from __future__ import annotations

import math
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db_v2
from app.errors import AppError
from app.schemas import (
    AgencyList, LegShapeResponse, RouteShapesGeometry, RouteShapeGeometry, RouteDetail, RouteList, RouteShapes, ShapeResponse, StopTimeList, TripDetail, TripList,
)
from app.services import leg_service
from app.services import network_service as net
from app.services import shape_service as shapes

router = APIRouter()
Db = Annotated[sqlite3.Connection, Depends(get_db_v2)]
Offset = Annotated[int, Query(ge=0, le=1_000_000)]
ShapeFormat = Annotated[Literal["points", "geojson"], Query(description="'geojson' returns a LineString Feature")]


@router.get("/agencies", response_model=AgencyList, tags=["agencies"], summary="Agencies of the feed")
def agencies(conn: Db) -> AgencyList:
    return net.list_agencies(conn)


@router.get("/routes", response_model=RouteList, tags=["routes"], summary="List routes (paginated, filterable)")
def routes(
    conn: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=100, description="Part of route_short_name / route_long_name")] = None,
    agency_id: Annotated[str | None, Query(max_length=255)] = None,
    route_type: Annotated[int | None, Query(ge=0, le=9999)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Offset = 0,
) -> RouteList:
    return net.list_routes(conn, q.strip() if q else None, agency_id, route_type, limit, offset)


@router.get("/routes/{route_id}", response_model=RouteDetail, tags=["routes"], summary="Route details with shapes and trip counts")
def route_detail(conn: Db, route_id: str) -> RouteDetail:
    return net.get_route(conn, route_id)


@router.get("/routes/{route_id}/trips", response_model=TripList, tags=["routes"], summary="Trips of a route (paginated)")
def route_trips(
    conn: Db, route_id: str,
    service_id: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Offset = 0,
) -> TripList:
    return net.list_route_trips(conn, route_id, service_id, limit, offset)


@router.get("/routes/{route_id}/shapes", response_model=RouteShapes | RouteShapesGeometry, tags=["shapes"], summary="Shapes used by a route's trips (optionally with simplified geometry)")
def route_shapes(
    conn: Db, route_id: str,
    geometry: Annotated[bool, Query(description="Phase 4: include simplified [lon, lat] coordinates per shape")] = False,
    tolerance_m: Annotated[float | None, Query(description="Phase 4: simplification tolerance in metres (clamped to 1-50, default 5)")] = None,
    max_points: Annotated[int, Query(ge=10, le=5000, description="Phase 4: hard cap on returned points per shape")] = 2000,
) -> RouteShapes | RouteShapesGeometry:
    result = shapes.get_route_shapes(conn, route_id)
    if geometry:
        if tolerance_m is not None and not math.isfinite(tolerance_m):
            raise AppError(422, "validation_error", "tolerance_m must be a finite number.")
        items = leg_service.route_shapes_geometry(conn, route_id, [i.model_dump() for i in result.items], tolerance_m, max_points)
        return RouteShapesGeometry(route_id=route_id, items=[RouteShapeGeometry(**i) for i in items])
    return result


@router.get("/trips/{trip_id}", response_model=TripDetail, tags=["trips"], summary="Trip details")
def trip_detail(conn: Db, trip_id: str) -> TripDetail:
    return net.get_trip(conn, trip_id)


@router.get("/trips/{trip_id}/stop-times", response_model=StopTimeList, tags=["trips"], summary="Ordered stop times of one trip (paginated)")
def trip_stop_times(
    conn: Db, trip_id: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Offset = 0,
) -> StopTimeList:
    return net.list_trip_stop_times(conn, trip_id, limit, offset)


@router.get("/trips/{trip_id}/shape", response_model=LegShapeResponse | ShapeResponse, tags=["shapes"],
            summary="GTFS shape of a trip, or (with from_stop_id + to_stop_id) the simplified slice between two stops")
def trip_shape(
    conn: Db, trip_id: str,
    format: ShapeFormat = "points",
    fallback: Annotated[Literal["stops"] | None, Query(description="If the trip has no shape, return its stops as a labelled polyline")] = None,
    limit: Annotated[int, Query(ge=1, le=50_000)] = 5000,
    offset: Offset = 0,
    from_stop_id: Annotated[str | None, Query(min_length=1, max_length=255, description="Phase 4: boarding stop (with to_stop_id selects leg mode)")] = None,
    to_stop_id: Annotated[str | None, Query(min_length=1, max_length=255, description="Phase 4: alighting stop")] = None,
    board: Annotated[str | None, Query(max_length=8, description="Phase 4: boarding departure HH:MM[:SS], picks the right call on loop trips")] = None,
    tolerance_m: Annotated[float | None, Query(description="Phase 4: simplification tolerance in metres (clamped to 1-50, default 5)")] = None,
) -> LegShapeResponse | ShapeResponse:
    if (from_stop_id is None) != (to_stop_id is None):
        raise AppError(422, "validation_error", "from_stop_id and to_stop_id must be given together.")
    if from_stop_id is not None and to_stop_id is not None:
        if tolerance_m is not None and not math.isfinite(tolerance_m):
            raise AppError(422, "validation_error", "tolerance_m must be a finite number.")
        return LegShapeResponse(**leg_service.get_leg_shape(conn, trip_id, from_stop_id, to_stop_id, board=board, tolerance_m=tolerance_m))
    return shapes.get_trip_shape(conn, trip_id, fmt=format, fallback=fallback, limit=limit, offset=offset)


@router.get("/shapes/{shape_id}", response_model=ShapeResponse, tags=["shapes"], summary="A shape by id")
def shape_by_id(
    conn: Db, shape_id: str,
    format: ShapeFormat = "points",
    limit: Annotated[int, Query(ge=1, le=50_000)] = 5000,
    offset: Offset = 0,
) -> ShapeResponse:
    return shapes.get_shape(conn, shape_id, fmt=format, limit=limit, offset=offset)
