#!/usr/bin/env python3
"""Insert a clearly labeled three-day simulated TelosB dataset into MongoDB."""

import argparse
import math
import random
from datetime import datetime, timedelta, timezone

from pymongo import ASCENDING, MongoClient

from ingest import sht11_values


SCENARIO = "demo-3days-v1"
SOURCE_IDS = (1, 2)


def humidity_raw_for(target_pct, temperature_raw):
    low, high = 0, 4095
    while low < high:
        middle = (low + high) // 2
        _, measured = sht11_values(temperature_raw, middle)
        if measured < target_pct:
            low = middle + 1
        else:
            high = middle
    return low


def make_document(timestamp, source_id, count, rng):
    local_hour = (timestamp.hour + 3 + timestamp.minute / 60.0) % 24
    daylight = max(0.0, math.sin(math.pi * (local_hour - 6) / 12.0))
    daily_wave = math.sin(2 * math.pi * (local_hour - 8) / 24.0)
    temperature_target = 28.2 + 3.5 * daily_wave + 0.5 * source_id
    temperature_target += rng.gauss(0, 0.18)
    humidity_target = 46.0 - 8.0 * daily_wave - 0.7 * source_id
    humidity_target += rng.gauss(0, 0.8)
    temperature_raw = int(round((temperature_target + 39.6) * 100))
    humidity_raw = humidity_raw_for(humidity_target, temperature_raw)
    temperature_c, humidity_pct = sht11_values(temperature_raw, humidity_raw)
    photo_raw = max(1, int(5 + 110 * daylight + rng.gauss(0, 3)))
    solar_raw = max(1, int(3 + 140 * daylight + rng.gauss(0, 3)))
    raw_line = (
        "parent=0 src={} count={} humidity={} temperature={} photo={} solar={}"
        .format(source_id, count, humidity_raw, temperature_raw,
                photo_raw, solar_raw)
    )
    return {
        "_id": "{}-{}-{}".format(SCENARIO, source_id, count),
        "timestamp": timestamp,
        "parent_id": 0,
        "source_id": source_id,
        "count": count,
        "temperature_raw": temperature_raw,
        "humidity_raw": humidity_raw,
        "photo_raw": photo_raw,
        "solar_raw": solar_raw,
        "temperature_c": temperature_c,
        "humidity_pct": humidity_pct,
        "raw_line": raw_line,
        "data_origin": "synthetic",
        "scenario_id": SCENARIO,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", default="mongodb://127.0.0.1:27017/")
    parser.add_argument("--db", default="iot_wsn")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--interval", type=int, default=20)
    args = parser.parse_args()
    if args.days <= 0 or args.interval <= 0:
        parser.error("days and interval must be positive")

    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    collection = client[args.db].synthetic_measurements
    collection.create_index([("source_id", ASCENDING), ("timestamp", ASCENDING)])
    collection.delete_many({"scenario_id": SCENARIO})

    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(days=args.days)
    steps = args.days * 86400 // args.interval
    rng = random.Random(20260929)
    batch = []
    inserted = 0
    for count in range(steps):
        timestamp = start + timedelta(seconds=count * args.interval)
        for source_id in SOURCE_IDS:
            batch.append(make_document(timestamp, source_id, count, rng))
        if len(batch) >= 500:
            collection.insert_many(batch)
            inserted += len(batch)
            batch = []
    if batch:
        collection.insert_many(batch)
        inserted += len(batch)
    client.close()
    print("Inserted {} synthetic measurements, {} sources, {} to {} UTC".format(
        inserted, len(SOURCE_IDS), start.isoformat(),
        (end - timedelta(seconds=args.interval)).isoformat()
    ))


if __name__ == "__main__":
    main()
