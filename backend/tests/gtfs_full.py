"""A small but *complete* synthetic GTFS feed: every supported file, shapes out of order, overnight times.

Test-only data. Calendar: S1 runs every day 2025-01-01..2040-12-31; S2 is added on 2026-11-09 and S1 is removed on
2026-11-10 (via calendar_dates).
"""

from __future__ import annotations

from tests.gtfs_factory import FILES

FULL_FILES: dict[str, str] = {
    **FILES,
    "agency.txt": "agency_id,agency_name,agency_url,agency_timezone,agency_lang\n"
                  "AG1,Alpha Transit,https://alpha.example/,Asia/Kolkata,en\n"
                  "AG2,Beta Transit,https://beta.example/,Asia/Kolkata,en\n",
    "stops.txt": "stop_id,stop_code,stop_name,stop_lat,stop_lon,level_id\n"
                 "A,CA,Alpha Stop,28.60,77.20,L0\nB,CB,Beta Stop,28.61,77.21,\n"
                 "C,CC,Gamma 50%_Stop,28.62,77.22,\nD,CD,Delta Stop,28.63,77.23,\n",
    "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type,route_desc\n"
                  "R1,AG1,101,Alpha to Gamma,3,Express\nR2,AG2,NIGHT,,3,\n",
    "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n"
                 "R1,S1,T1,Gamma,0,SH1\nR1,S1,T2,Gamma,0,SH1\nR2,S1,T3,Beta,1,\nR1,S2,T4,Delta,0,SH2\n",
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,timepoint,fare_stage\n"
        "T1,08:00:00,08:00:00,A,1,0,1,0\nT1,08:10:00,08:10:00,B,2,,0,1\nT1,08:20:00,08:20:00,C,3,,1,1\n"
        "T2,09:00:00,09:00:00,A,1,,1,0\nT2,09:10:00,09:10:00,B,5,,0,1\nT2,09:20:00,09:20:00,C,9,,1,1\n"  # sparse sequences
        "T3,23:50:00,23:50:00,A,1,,1,0\nT3,24:10:00,24:10:00,B,2,,1,0\n"
        "T4,10:00:00,10:00:00,A,1,,1,0\nT4,10:30:00,10:30:00,D,2,,1,1\n"
    ),
    "shapes.txt": (  # SH1 deliberately NOT in sequence order in the file
        "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence,shape_dist_traveled\n"
        "SH1,28.62,77.22,3,2500.5\nSH1,28.60,77.20,1,0\nSH1,28.61,77.21,2,1200.25\n"
        "SH2,28.60,77.20,1,0\nSH2,28.63,77.23,2,4200\n"
    ),
    "feed_info.txt": "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version\n"
                     "Example Publisher,https://pub.example/,en,20250101,20401231,v7\n",
    "frequencies.txt": "trip_id,start_time,end_time,headway_secs,exact_times\nT1,8:00:00,10:00:00,600,0\n",
    "transfers.txt": "from_stop_id,to_stop_id,transfer_type,min_transfer_time\nB,C,2,120\n",
    "levels.txt": "level_id,level_index,level_name\nL0,0,Ground\n",
    "pathways.txt": "pathway_id,from_stop_id,to_stop_id,pathway_mode,is_bidirectional,length\nP1,A,B,1,1,12.5\n",
    "attributions.txt": "attribution_id,organization_name,is_producer\nAT1,Example Org,1\n",
    "fare_attributes.txt": "fare_id,price,currency_type,payment_method,transfers\nF1,10.00,inr,0,\n",
    "fare_rules.txt": "fare_id,route_id\nF1,R1\n",
}

FULL_COUNTS = {
    "agency": 2, "stops": 4, "levels": 1, "routes": 2, "trips": 4, "calendar": 1, "calendar_dates": 2, "shapes": 2,
    "shape_points": 5, "stop_times": 10, "frequencies": 1, "transfers": 1, "pathways": 1, "attributions": 1,
    "fare_attributes": 1, "fare_rules": 1, "feed_info": 1,
}
