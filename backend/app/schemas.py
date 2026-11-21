"""Pydantic response models: the public API contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import model_serializer, BaseModel, Field


# --- stops ------------------------------------------------------------------

class _OmitNullClusterId(BaseModel):
    """Phase 4: ``cluster_id`` is additive. It is left out entirely (not ``null``) when no cluster is known, so responses
    from a database without derived data are byte-for-byte what Phase 1-3 clients already receive."""
    cluster_id: str | None = None

    @model_serializer(mode="wrap")
    def _drop_null_cluster_id(self, handler):
        data = handler(self)
        if data.get("cluster_id") is None:
            data.pop("cluster_id", None)
        return data


class Stop(BaseModel):
    stop_id: str
    stop_name: str
    stop_lat: float | None = None
    stop_lon: float | None = None


class StopWithCluster(Stop, _OmitNullClusterId):
    """Phase 4 (additive): a search/list item that also names its place cluster (omitted until derived data is built)."""


class StopSearchResponse(BaseModel):
    items: list[StopWithCluster]
    # Phase 1 pagination fields (additive; Phase 0 clients only read ``items``)
    total: int | None = None
    limit: int | None = None
    offset: int | None = None


# --- journeys ---------------------------------------------------------------

class CrowdInfo(BaseModel):
    """Crowd information. Until official ETM data exists this is always NOT_AVAILABLE."""

    status: Literal["NOT_AVAILABLE"] = "NOT_AVAILABLE"
    label: str = "Crowd data not connected"


class JourneyItem(BaseModel):
    trip_id: str
    route_id: str
    route_name: str
    origin: str
    destination: str
    departure: str = Field(description="Local ISO datetime of scheduled departure")
    arrival: str = Field(description="Local ISO datetime of scheduled arrival")
    scheduled_duration_minutes: int
    intermediate_stops: int
    crowd: CrowdInfo
    data_basis: str


class JourneySearchResponse(BaseModel):
    items: list[JourneyItem]
    mode: str | None = None
    notice: str | None = None
    message: str | None = None


# --- health -----------------------------------------------------------------

class ComponentStatus(BaseModel):
    status: str
    detail: str | None = None


class GtfsCheck(BaseModel):
    status: Literal["ready", "not_ready", "unknown"]
    detail: str | None = None
    problems: list[str] = Field(default_factory=list)
    counts: dict[str, int] | None = None
    imported_at: str | None = None
    feed_version: str | None = None
    feed_start_date: str | None = None
    feed_end_date: str | None = None
    last_import_attempt: dict[str, Any] | None = None


class HealthChecks(BaseModel):
    application: ComponentStatus
    database: ComponentStatus
    gtfs: GtfsCheck
    crowd_engine: ComponentStatus


class HealthResponse(BaseModel):
    status: Literal["ok", "needs_setup", "error"]
    version: str
    timestamp: str
    checks: HealthChecks
    # Legacy top-level fields kept for backward compatibility with existing clients.
    gtfs_loaded: bool
    counts: dict[str, int] | None = None
    crowd_engine: str


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


# --- errors -----------------------------------------------------------------

class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
    detail: str = Field(description="Same text as error.message; kept for pre-Phase-0 clients")


# =============================================================================
# Phase 1: GTFS query API (all values come from the imported feed, never invented)
# =============================================================================

class Page(BaseModel):
    total: int = Field(description="Rows matching the filters (not just this page)")
    limit: int
    offset: int


class AgencyOut(BaseModel):
    agency_id: str = Field(description="Empty string = the feed's only agency, which omitted agency_id")
    agency_name: str
    agency_url: str
    agency_timezone: str
    agency_lang: str | None = None
    agency_phone: str | None = None
    agency_fare_url: str | None = None
    agency_email: str | None = None


class AgencyList(BaseModel):
    items: list[AgencyOut]
    total: int


class RouteRef(BaseModel):
    route_id: str
    route_short_name: str | None = None
    route_long_name: str | None = None


class StopRoute(RouteRef):
    stop_time_count: int = Field(description="Scheduled stop_times of this route at the stop (all services)")


class StopDetail(_OmitNullClusterId):
    stop_id: str
    stop_name: str | None = None
    stop_lat: float | None = None
    stop_lon: float | None = None
    stop_code: str | None = None
    stop_desc: str | None = None
    zone_id: str | None = None
    stop_url: str | None = None
    location_type: int | None = None
    parent_station: str | None = None
    stop_timezone: str | None = None
    wheelchair_boarding: int | None = None
    platform_code: str | None = None
    stop_time_count: int
    routes: list[StopRoute]


class Departure(BaseModel):
    trip_id: str
    route_id: str
    route_short_name: str | None = None
    route_long_name: str | None = None
    trip_headsign: str | None = None
    stop_sequence: int
    departure_time: str = Field(description="GTFS time on the trip's service day; may be 24:00:00 or later")
    departure: str = Field(description="Local ISO datetime of the departure (service day + GTFS time)")
    service_date: str = Field(description="Service day the trip belongs to (YYYY-MM-DD)")
    pickup_type: int | None = None


class DeparturesResponse(BaseModel):
    stop_id: str
    date: str
    after: str
    items: list[Departure]
    notice: str


class RouteItem(BaseModel):
    route_id: str
    agency_id: str | None = None
    route_short_name: str | None = None
    route_long_name: str | None = None
    route_desc: str | None = None
    route_type: int
    route_color: str | None = None


class RouteList(Page):
    items: list[RouteItem]


class RouteShapeRef(BaseModel):
    shape_id: str | None
    trip_count: int
    point_count: int | None = None


class RouteShapeGeometry(RouteShapeRef):
    """Phase 4: a route shape reference plus simplified geometry (only returned with ?geometry=true)."""
    geometry_status: Literal["ok", "no_shape"]
    coordinates: list[list[float]] = Field(default_factory=list, description="[lon, lat] pairs, original vertices")
    point_count_original: int | None = None
    point_count_returned: int | None = None
    simplified: bool | None = None
    tolerance_m: float | None = None
    data_basis: Literal["gtfs_shape"] | None = None


class RouteShapesGeometry(BaseModel):
    route_id: str
    items: list[RouteShapeGeometry]


class RouteDetail(RouteItem):
    route_url: str | None = None
    route_text_color: str | None = None
    route_sort_order: int | None = None
    agency: AgencyOut | None = None
    trip_count: int
    stop_count: int = Field(description="Distinct stops served by any trip of the route")
    service_ids: list[str]
    directions: dict[str, int] = Field(description="Trips per direction_id ('unspecified' when the feed has none)")
    shapes: list[RouteShapeRef]


class TripItem(BaseModel):
    trip_id: str
    route_id: str
    service_id: str
    trip_headsign: str | None = None
    direction_id: int | None = None
    shape_id: str | None = None
    first_departure: str | None = None


class TripList(Page):
    items: list[TripItem]


class StopEnd(BaseModel):
    stop_id: str
    stop_name: str | None = None
    stop_sequence: int
    time: str | None = None


class TripDetail(BaseModel):
    trip_id: str
    route_id: str
    route_short_name: str | None = None
    route_long_name: str | None = None
    service_id: str
    trip_headsign: str | None = None
    trip_short_name: str | None = None
    direction_id: int | None = None
    block_id: str | None = None
    shape_id: str | None = None
    wheelchair_accessible: int | None = None
    bikes_allowed: int | None = None
    has_shape: bool
    stop_count: int
    first_stop: StopEnd | None = None
    last_stop: StopEnd | None = None


class StopTimeItem(BaseModel):
    stop_sequence: int
    stop_id: str
    stop_name: str | None = None
    stop_lat: float | None = None
    stop_lon: float | None = None
    arrival_time: str | None = None
    departure_time: str | None = None
    pickup_type: int | None = None
    drop_off_type: int | None = None
    timepoint: int | None = None
    shape_dist_traveled: float | None = None
    fare_stage: int | None = Field(default=None, description="Non-GTFS extension present in the Delhi feed")


class StopTimeList(Page):
    trip_id: str
    items: list[StopTimeItem]


class ShapePoint(BaseModel):
    lat: float
    lon: float
    sequence: int
    dist_traveled: float | None = None


class ShapeResponse(BaseModel):
    trip_id: str | None = None
    shape_id: str | None = None
    shape_available: bool
    geometry_source: Literal["gtfs_shape", "stop_sequence_fallback", "none"]
    reason: str | None = Field(default=None, description="Why no GTFS shape is available, when that is the case")
    note: str | None = None
    point_count: int = Field(description="Points in the full shape (or fallback polyline)")
    offset: int = 0
    returned_points: int
    bbox: list[float] | None = Field(default=None, description="[min_lon, min_lat, max_lon, max_lat]")
    max_dist_traveled: float | None = Field(default=None, description="Largest shape_dist_traveled, in the feed's own units")
    points: list[ShapePoint] = Field(default_factory=list)
    geojson: dict[str, Any] | None = None


class RouteShapes(BaseModel):
    route_id: str
    items: list[RouteShapeRef]


class ServiceOut(BaseModel):
    service_id: str
    active: bool
    reason: str
    trip_count: int


class ActiveServicesResponse(BaseModel):
    date: str
    weekday: str
    date_source: Literal["request", "today_in_feed_timezone"]
    timezone: str | None = None
    active_service_ids: list[str]
    active_count: int
    inactive_count: int
    calendar_dates_present: bool
    services: list[ServiceOut]


class GtfsSummary(BaseModel):
    schema_version: int
    imported_at: str | None = None
    source_zip_name: str | None = None
    source_sha256: str | None = None
    feed: list[dict[str, Any]]
    agencies: list[AgencyOut]
    counts: dict[str, int]
    bounds: dict[str, float] | None = None
    routes_by_type: dict[str, int]
    calendar: dict[str, Any]
    shapes: dict[str, Any]
    data_quality: dict[str, Any] | None = None
    data_scope: dict[str, str]


class ValidationReport(BaseModel):
    schema_version: int
    imported_at: str | None = None
    source_sha256: str | None = None
    data_quality: dict[str, Any] | None = Field(description="Findings and integrity checks of the data in this database")
    files: list[dict[str, Any]]
    missing_optional_files: list[str]
    recognised_unimported_files: list[str]
    unrecognised_files: list[str]
    column_usage: dict[str, dict[str, int]]
    last_import_attempt: dict[str, Any] | None = Field(
        description="Outcome of the most recent import attempt. Reported separately from data quality: a failed "
                    "attempt never changes the database that is being served.")


class StopMatch(BaseModel):
    stop_id: str
    distance_to_shape_m: float | None = None


class LegShapeResponse(BaseModel):
    """Phase 4: the slice of a trip's GTFS shape between two of its stops (additive; the Phase 1 shape response is unchanged)."""
    status: Literal["ok", "no_shape", "unreliable_projection"]
    reason: str | None = None
    trip_id: str
    shape_id: str | None = None
    data_basis: Literal["gtfs_shape"] = "gtfs_shape"
    coordinates: list[list[float]] = Field(default_factory=list, description="[lon, lat] pairs")
    point_count_original: int | None = None
    point_count_returned: int | None = None
    simplified: bool | None = None
    tolerance_m: float
    length_m: float | None = None
    length_original_m: float | None = None
    match_method: Literal["projection", "shape_dist_traveled"] | None = None
    match_threshold_m: float | None = None
    boarding: StopMatch | None = None
    alighting: StopMatch | None = None


class NearbyStop(BaseModel):
    stop_id: str
    stop_name: str | None
    stop_lat: float
    stop_lon: float
    distance_m: int = Field(description="Straight-line metres, rounded to 1 m (not a walking distance)")
    bearing_deg: int = Field(ge=0, le=359, description="Compass bearing from the query point to the stop")
    compass: Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    routes_count: int
    route_names: list[str] = Field(description="Up to 5 serving routes, most scheduled calls first")
    cluster_id: str | None = None


class NearbyResponse(BaseModel):
    radius_m: int
    limit: int
    total_in_radius: int
    returned: int
    index: Literal["rtree", "grid", "scan"]
    items: list[NearbyStop]
    data_basis: Literal["gtfs_stops"] = "gtfs_stops"
    notice: str


class ClusterMember(BaseModel):
    stop_id: str
    stop_name: str | None
    stop_lat: float
    stop_lon: float
    distance_from_centroid_m: int
    bearing_from_centroid_deg: int | None = Field(description="null for a single-stop cluster (it IS the centroid)")
    compass: str | None
    routes_count: int
    route_names: list[str]
    scheduled_calls: int = Field(description="stop_times rows at this stop in the static timetable (all days)")
    headsigns: list[str] = Field(description="Distinct non-empty trip/stop headsigns of trips serving this stop; empty when the feed has none")


class ClusterResponse(BaseModel):
    cluster_id: str
    display_name: str
    centroid_lat: float
    centroid_lon: float
    stop_count: int
    members: list[ClusterMember]
    rule: str
    threshold_m: float
    headsigns_available: bool
    notice: str


class SmartMember(BaseModel):
    stop_id: str
    stop_name: str
    stop_lat: float | None = None
    stop_lon: float | None = None
    routes_count: int
    route_names: list[str]
    match_type: Literal["exact", "alias", "prefix", "all_tokens", "partial_tokens", "fuzzy"]
    score: int


class SmartGroup(BaseModel):
    cluster_id: str | None
    display_name: str
    stop_count: int
    centroid_lat: float | None = None
    centroid_lon: float | None = None
    match_type: Literal["exact", "alias", "prefix", "all_tokens", "partial_tokens", "fuzzy"]
    score: int
    members: list[SmartMember]


class SmartSearchItem(SmartMember):
    cluster_id: str | None = None


class SmartSearchResponse(BaseModel):
    query: str
    mode: Literal["smart"] = "smart"
    limit: int
    total_groups: int
    returned_groups: int
    groups: list[SmartGroup]
    items: list[SmartSearchItem] = Field(description="The same stops, flattened in ranked order")
    notice: str | None = None
