# Phase 4 API changes

All changes are **additive**: no existing endpoint, parameter or response field was removed or renamed, and responses from a database without derived data are byte-for-byte what Phase 3 clients receive. Every example below is a real request/response from the running server against the real Delhi GTFS database (long coordinate / item arrays are shortened and marked `... N more`; nothing else is edited). Regenerate with `python -m scripts.build_derived`, start the server, and re-run the requests.

| Endpoint | Change |
|---|---|
| `GET /trips/{trip_id}/shape?from_stop_id&to_stop_id[&board][&tolerance_m]` | **New mode** on an existing endpoint (both stop params together). Without them: unchanged Phase 1 behaviour. |
| `GET /routes/{route_id}/shapes?geometry=true[&tolerance_m][&max_points]` | **New opt-in** field set on an existing endpoint. Default response unchanged. |
| `GET /stops/nearby?lat&lon[&radius_m][&limit]` | **New** |
| `GET /clusters/{cluster_id}` | **New** |
| `GET /stops?q=…&mode=smart[&limit]` | **New mode**; default `mode=substring` unchanged |
| `cluster_id` on `GET /stops/{id}` and `/stops` items | **New optional field**, omitted entirely when derived data is not built |

## Error format

Unchanged: `{"error": {"code": "...", "message": "..."}}`. New codes: `location_out_of_area` (422), `stop_not_on_trip` (404), `alight_before_board` (422), `cluster_not_found` (404), `derived_data_missing` (503).

### 1. Leg geometry: real GTFS shape between two stops of a trip (`status: ok`)

Trip `72_06_40`, first to last stop. `coordinates` are `[lon, lat]`, sliced from the trip's GTFS shape with interpolated end points and simplified (Ramer–Douglas–Peucker in metres, default 5 m). `match_method` is `projection` because this feed has no `stop_times.shape_dist_traveled` (see EVIDENCE.md M1).

```
GET /api/v1/trips/72_06_40/shape?from_stop_id=7572&to_stop_id=384&board=06%3A40%3A00
→ HTTP 200  (4,332 bytes)
```
```json
{
  "status": "ok",
  "reason": null,
  "trip_id": "72_06_40",
  "shape_id": "shp_3_1761",
  "data_basis": "gtfs_shape",
  "coordinates": [
    [
      77.227364,
      28.66013
    ],
    [
      77.223938,
      28.660429
    ],
    [
      77.223389,
      28.660704
    ],
    "... 176 more [lon,lat] pairs"
  ],
  "point_count_original": 607,
  "point_count_returned": 179,
  "simplified": true,
  "tolerance_m": 5.0,
  "length_m": 40722.2,
  "length_original_m": 40765.2,
  "match_method": "projection",
  "match_threshold_m": 60.0,
  "boarding": {
    "stop_id": "7572",
    "distance_to_shape_m": 52.2
  },
  "alighting": {
    "stop_id": "384",
    "distance_to_shape_m": 5.6
  }
}
```

### 2. Leg geometry: loop trip, whole loop (longest shape in the feed)

Boarding and alighting stop are the same stop id; alighting is the first *later* call, so the whole loop is returned. `tolerance_m=20` is accepted (the allowed range is clamped to 1–50 m).

```
GET /api/v1/trips/2716_04_50/shape?from_stop_id=4947&to_stop_id=4947&tolerance_m=20
→ HTTP 200  (4,424 bytes)
```
```json
{
  "status": "ok",
  "reason": null,
  "trip_id": "2716_04_50",
  "shape_id": "shp_3_883",
  "data_basis": "gtfs_shape",
  "coordinates": [
    [
      77.316966,
      28.644973
    ],
    [
      77.319115,
      28.651518
    ],
    [
      77.319214,
      28.652582
    ],
    "... 181 more [lon,lat] pairs"
  ],
  "point_count_original": 1319,
  "point_count_returned": 184,
  "simplified": true,
  "tolerance_m": 20.0,
  "length_m": 105845.1,
  "length_original_m": 106609.5,
  "match_method": "projection",
  "match_threshold_m": 60.0,
  "boarding": {
    "stop_id": "4947",
    "distance_to_shape_m": 0.2
  },
  "alighting": {
    "stop_id": "4947",
    "distance_to_shape_m": 9.7
  }
}
```

### 3. Leg geometry: structured non-ok outcomes

The real Delhi feed has no trip without a shape and no unreliable data in the sampled legs of that route, so these two shapes are shown **from the synthetic test world** (`backend/tests/geo_world.py`), exactly as the test-suite asserts them. In the real feed, 5 of 293 randomly sampled legs were `unreliable_projection` (EVIDENCE.md M3).

```json
// trip without a shape: HTTP 200, never a guess
{"status": "no_shape", "reason": "trip_has_no_shape_id", "coordinates": [], "boarding": null, "alighting": null, "data_basis": "gtfs_shape", "tolerance_m": 5.0, "...": "..."}
// a stop farther than 60 m from the shape: HTTP 200, no line
{"status": "unreliable_projection", "reason": "alighting_stop_farther_than_60m_from_shape", "coordinates": [], "boarding": {"stop_id": "S0", "distance_to_shape_m": 11.1}, "alighting": {"stop_id": "FAR", "distance_to_shape_m": 556.4}, "match_threshold_m": 60.0, "...": "..."}
```

### 4. Route shapes with simplified geometry

Opt-in. Coordinates are original shape vertices (no resampling). `max_points` (10–5000, default 2000) is a hard cap: if the line still exceeds it the tolerance is doubled until it fits and the tolerance used is reported.

```
GET /api/v1/routes/2716/shapes?geometry=true&tolerance_m=5
→ HTTP 200  (9,234 bytes)
```
```json
{
  "route_id": "2716",
  "items": [
    {
      "shape_id": "shp_3_883",
      "trip_count": 67,
      "point_count": 1501,
      "geometry_status": "ok",
      "coordinates": [
        [
          77.316841,
          28.645031
        ],
        [
          77.31691,
          28.644823
        ],
        [
          77.317978,
          28.647888
        ],
        "... 410 more [lon,lat] pairs"
      ],
      "point_count_original": 1501,
      "point_count_returned": 413,
      "simplified": true,
      "tolerance_m": 5.0,
      "data_basis": "gtfs_shape"
    }
  ]
}
```

### 5. Nearby stops

Straight-line distances, nearest first (ties by stop id). `index` says which spatial index answered (`rtree`, `grid`, or `scan` when derived data is not built). Coordinates in the query are never logged (OPERATIONS.md).

```
GET /api/v1/stops/nearby?lat=28.6663&lon=77.2287&radius_m=300&limit=3
→ HTTP 200  (1,092 bytes)
```
```json
{
  "radius_m": 300,
  "limit": 3,
  "total_in_radius": 9,
  "returned": 3,
  "index": "rtree",
  "items": [
    {
      "stop_id": "4822",
      "stop_name": "ISBT Kashmere Gate City Bus Terminal / ISBT Maharana Pratap Bus Terminal",
      "stop_lat": 28.66676253341815,
      "stop_lon": 77.22941348231966,
      "distance_m": 87,
      "bearing_deg": 54,
      "compass": "NE",
      "routes_count": 68,
      "route_names": [
        "GL-23UP",
        "192UP",
        "405DOWN",
        "0261(NS)UP",
        "0405(NS)DOWN"
      ],
      "cluster_id": "c_752850d25707"
    },
    {
      "stop_id": "4821",
      "stop_name": "ISBT Kashmere Gate (Lothian Road)",
      "stop_lat": 28.66618357837201,
      "stop_lon": 77.22970858182461,
      "distance_m": 99,
      "bearing_deg": 97,
      "compass": "E",
      "routes_count": 46,
      "route_names": [
        "144DOWN",
        "405UP",
        "0405(NS)UP",
        "213DOWN",
        "141DOWN"
      ],
      "cluster_id": "c_7091ea48a07d"
    },
    {
      "stop_id": "4109",
      "stop_name": "ISBT Kashmere Gate Terminal",
      "stop_lat": 28.66696,
      "stop_lon": 77.227456,
      "distance_m": 142,
      "bearing_deg": 301,
      "compass": "NW",
      "routes_count": 14,
      "route_names": [
        "502UP",
        "429UP",
        "258UP",
        "721UP",
        "425UP"
      ],
      "cluster_id": "c_fcd6e47442fb"
    }
  ],
  "data_basis": "gtfs_stops",
  "notice": "Distances are straight-line from the given point to each stop; they are not walking distances."
}
```

### 6. Nearby: outside Delhi-NCR is a clear 422, not an empty list

Service area: 28.00–29.50 N, 76.40–77.80 E (contains all 6,812 stops).

```
GET /api/v1/stops/nearby?lat=19.076&lon=72.8777
→ HTTP 422  (296 bytes)
```
```json
{
  "error": {
    "code": "location_out_of_area",
    "message": "This location is outside the Delhi-NCR service area (28.0-29.5 N, 76.4-77.8 E). CrowdSense only has Delhi bus data."
  },
  "detail": "This location is outside the Delhi-NCR service area (28.0-29.5 N, 76.4-77.8 E). CrowdSense only has Delhi bus data."
}
```

### 7. Nearby: invalid radius

`radius_m` 50–3000, `limit` 1–50.

```
GET /api/v1/stops/nearby?lat=28.6&lon=77.2&radius_m=49
→ HTTP 422  (233 bytes)
```
```json
{
  "error": {
    "code": "validation_error",
    "message": "Invalid request parameters.",
    "details": [
      {
        "field": "radius_m",
        "message": "Input should be greater than or equal to 50",
        "type": "greater_than_equal"
      }
    ]
  },
  "detail": "Invalid request parameters."
}
```

### 8. Place cluster

Members are distinguished only by real data: coordinates, routes serving the stop (route names such as `…UP`/`…DOWN` come from the feed), bearing/distance from the centroid and scheduled call count. `headsigns` is empty and `headsigns_available` false because this feed publishes none: nothing is invented.

```
GET /api/v1/clusters/c_465c7d6aa21a
→ HTTP 200  (1,786 bytes)
```
```json
{
  "cluster_id": "c_465c7d6aa21a",
  "display_name": "Rithala Metro Station",
  "centroid_lat": 28.720376280413777,
  "centroid_lon": 77.10809815524468,
  "stop_count": 4,
  "members": [
    {
      "stop_id": "15",
      "stop_name": "Rithala Metro Station",
      "stop_lat": 28.72043722070273,
      "stop_lon": 77.10767284913254,
      "distance_from_centroid_m": 42,
      "bearing_from_centroid_deg": 279,
      "compass": "W",
      "routes_count": 26,
      "route_names": [
        "141ADOWN",
        "141DOWN",
        "D-2301DOWN",
        "990EXTDOWN",
        "990CDOWN"
      ],
      "scheduled_calls": 862,
      "headsigns": []
    },
    {
      "stop_id": "4708",
      "stop_name": "Rithala Metro Station",
      "stop_lat": 28.720356,
      "stop_lon": 77.108354,
      "distance_from_centroid_m": 25,
      "bearing_from_centroid_deg": 95,
      "compass": "E",
      "routes_count": 6,
      "route_names": [
        "889DOWN",
        "D-3201DOWN",
        "D-3303DOWN",
        "D-3304DOWN",
        "889STLDOWN"
      ],
      "scheduled_calls": 184,
      "headsigns": []
    },
    "... 2 more items"
  ],
  "rule": "same normalised name + complete linkage",
  "threshold_m": 150.0,
  "headsigns_available": false,
  "notice": "Stops of one place share a name and lie within the cluster distance of each other. They are different physical stops (often opposite sides of a road): choose the specific stop you board at. The feed publishes no headsigns, so no 'towards' labels are shown unless headsigns exist."
}
```

### 9. Smart search (typo + reordered tokens)

Pipeline: normalise → candidates → rank → group by place cluster. `match_type` ∈ exact, alias, prefix, all_tokens, fuzzy, partial_tokens, with the numeric `score`.

```
GET /api/v1/stops?q=kashmire+gate&mode=smart&limit=2
→ HTTP 200  (1,347 bytes)
```
```json
{
  "query": "kashmire gate",
  "mode": "smart",
  "limit": 2,
  "total_groups": 11,
  "returned_groups": 2,
  "groups": [
    {
      "cluster_id": "c_de53e0f9c9dc",
      "display_name": "ISBT Kashmiri Gate",
      "stop_count": 1,
      "centroid_lat": 28.66800192893344,
      "centroid_lon": 77.22928246009047,
      "match_type": "fuzzy",
      "score": 475,
      "members": [
        {
          "stop_id": "6026",
          "stop_name": "ISBT Kashmiri Gate",
          "stop_lat": 28.66800192893344,
          "stop_lon": 77.22928246009047,
          "routes_count": 34,
          "route_names": [
            "214DOWN",
            "348UP",
            "131DOWN"
          ],
          "match_type": "fuzzy",
          "score": 475
        }
      ]
    },
    {
      "cluster_id": "c_81ecfd4383a1",
      "display_name": "ISBT Kashmere Gate",
      "stop_count": 1,
      "centroid_lat": 28.669372,
      "centroid_lon": 77.227137,
      "match_type": "fuzzy",
      "score": 475,
      "members": [
        {
          "stop_id": "267",
          "stop_name": "ISBT Kashmere Gate",
          "stop_lat": 28.669372,
          "stop_lon": 77.227137,
          "routes_count": 13,
          "route_names": [
            "103DOWN",
            "112DOWN",
            "143ADOWN"
          ],
          "match_type": "fuzzy",
          "score": 475
        }
      ]
    }
  ],
  "items": [
    {
      "stop_id": "6026",
      "stop_name": "ISBT Kashmiri Gate",
      "stop_lat": 28.66800192893344,
      "stop_lon": 77.22928246009047,
      "routes_count": 34,
      "route_names": [
        "214DOWN",
        "348UP",
        "131DOWN"
      ],
      "match_type": "fuzzy",
      "score": 475,
      "cluster_id": "c_de53e0f9c9dc"
    },
    {
      "stop_id": "267",
      "stop_name": "ISBT Kashmere Gate",
      "stop_lat": 28.669372,
      "stop_lon": 77.227137,
      "routes_count": 13,
      "route_names": [
        "103DOWN",
        "112DOWN",
        "143ADOWN"
      ],
      "match_type": "fuzzy",
      "score": 475,
      "cluster_id": "c_81ecfd4383a1"
    }
  ],
  "notice": null
}
```

### 10. Smart search: non-Latin input is an honest empty result

No transliteration dictionary is shipped (it would be invented data); an alias row with a verifiable `source` is the only way to add one.

```
GET /api/v1/stops?q=%E0%A4%95%E0%A4%B6%E0%A5%8D%E0%A4%AE%E0%A5%80%E0%A4%B0%E0%A5%80+%E0%A4%97%E0%A5%87%E0%A4%9F&mode=smart
→ HTTP 200  (269 bytes)
```
```json
{
  "query": "कश्मीरी गेट",
  "mode": "smart",
  "limit": 20,
  "total_groups": 0,
  "returned_groups": 0,
  "groups": [],
  "items": [],
  "notice": "No stop matches. Stop names in the feed are in Latin script; text in other scripts is not transliterated unless an alias exists."
}
```

### 11. Smart search: validation

Min 2 letters/digits after normalisation, max 80 characters, `limit` ≤ 50, only `q` and `limit` accepted with `mode=smart`.

```
GET /api/v1/stops?q=x&mode=smart
→ HTTP 422  (221 bytes)
```
```json
{
  "error": {
    "code": "validation_error",
    "message": "Invalid request parameters.",
    "details": [
      {
        "field": "q",
        "message": "String should have at least 2 characters",
        "type": "string_too_short"
      }
    ]
  },
  "detail": "Invalid request parameters."
}
```

### 12. `cluster_id` on a stop (additive)



```
GET /api/v1/stops/106
→ HTTP 200  (1,443 bytes)
```
```json
{
  "cluster_id": "c_7ac100c51be4",
  "stop_id": "106",
  "stop_name": "Banglow Road / Police Station Roop Nagar",
  "stop_lat": 28.684767,
  "stop_lon": 77.203767,
  "stop_code": "0718165A",
  "stop_desc": null,
  "zone_id": null,
  "stop_url": null,
  "location_type": null,
  "parent_station": null,
  "stop_timezone": null,
  "wheelchair_boarding": null,
  "platform_code": null,
  "stop_time_count": 181,
  "routes": [
    {
      "route_id": "1457",
      "route_short_name": "0114(NS)UP",
      "route_long_name": "0114(NS)UP",
      "stop_time_count": 1
    },
    {
      "route_id": "5",
      "route_short_name": "102DOWN",
      "route_long_name": "102DOWN",
      "stop_time_count": 16
    },
    "... 9 more items"
  ]
}
```
