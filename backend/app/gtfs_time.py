from datetime import datetime, timedelta

def gtfs_time_to_datetime(service_date: str, value: str) -> datetime:
    # GTFS service-day hours may exceed 23; do not use datetime.strptime(..., %H).
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    base = datetime.strptime(service_date, "%Y-%m-%d")
    return base + timedelta(hours=hours, minutes=minutes, seconds=seconds)

def duration_minutes(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() // 60))
