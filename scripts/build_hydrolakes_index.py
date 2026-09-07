#!/usr/bin/env python3
"""Build a compact North America HydroLAKES morphometry index for browser lookup.

Downloads the official HydroLAKES point shapefile ZIP, reads only its DBF attributes,
filters to Canada and northern U.S. lakes, and writes compact 2-degree JSON shards.
The original dataset is not redistributed in whole; this is a derived subset/index.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dbfread import DBF

SOURCE_URL = "https://data.hydrosheds.org/file/hydrolakes/HydroLAKES_points_v10_shp.zip"
FIELDS = ["hylak_id", "lat", "lon", "area_km2", "depth_m", "elevation_m", "shore_dev", "volume_mcm", "lake_type"]
CANADA = {"canada"}
USA = {"united states", "united states of america", "usa", "u.s.a.", "u.s."}


def fnum(v, default=0.0):
    try:
        x = float(v)
        return default if not math.isfinite(x) else x
    except (TypeError, ValueError):
        return default


def shard_key(lat: float, lon: float, size: int) -> str:
    y = math.floor(lat / size) * size
    x = math.floor(lon / size) * size
    return f"lat{y:+03d}_lon{x:+04d}"


def compact_row(r):
    return [
        int(r.get("Hylak_id") or 0),
        round(fnum(r.get("Pour_lat")), 5),
        round(fnum(r.get("Pour_long")), 5),
        round(fnum(r.get("Lake_area")), 3),
        round(fnum(r.get("Depth_avg")), 2),
        round(fnum(r.get("Elevation")), 1),
        round(fnum(r.get("Shore_dev")), 2),
        round(fnum(r.get("Vol_total")), 2),
        int(fnum(r.get("Lake_type"), 1)),
    ]


def download(url: str, path: Path):
    req = urllib.request.Request(url, headers={"User-Agent": "ChrisIzworski-IceOut/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, path.open("wb") as out:
        while True:
            block = resp.read(1024 * 1024)
            if not block:
                break
            out.write(block)


def build(output: Path, min_area: float, shard_size: int):
    output.mkdir(parents=True, exist_ok=True)
    for old in output.glob("lat*_lon*.json"):
        old.unlink()

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        zpath = td / "hydrolakes.zip"
        print(f"Downloading {SOURCE_URL}")
        download(SOURCE_URL, zpath)

        with zipfile.ZipFile(zpath) as zf:
            dbf_names = [n for n in zf.namelist() if n.lower().endswith(".dbf") and "points" in n.lower()]
            if not dbf_names:
                dbf_names = [n for n in zf.namelist() if n.lower().endswith(".dbf")]
            if not dbf_names:
                raise RuntimeError("HydroLAKES DBF not found in archive")
            dbf_name = dbf_names[0]
            print(f"Reading {dbf_name}")
            zf.extract(dbf_name, td)
            dbf_path = td / dbf_name

        shards = defaultdict(list)
        kept = 0
        scanned = 0
        countries = defaultdict(int)
        table = DBF(str(dbf_path), load=False, char_decode_errors="ignore")
        for r in table:
            scanned += 1
            country = str(r.get("Country") or "").strip().lower()
            lat = fnum(r.get("Pour_lat"), -999)
            area = fnum(r.get("Lake_area"), 0)
            if country in CANADA:
                pass
            elif country in USA and lat >= 40.0:
                pass
            else:
                continue
            if area < min_area:
                continue
            lon = fnum(r.get("Pour_long"), -999)
            if not (-180 <= lon <= -40 and 39 <= lat <= 85):
                continue
            row = compact_row(r)
            shards[shard_key(lat, lon, shard_size)].append(row)
            kept += 1
            countries[country] += 1
            if scanned % 250000 == 0:
                print(f"scanned={scanned:,} kept={kept:,}")

    for key, rows in shards.items():
        rows.sort(key=lambda x: (x[1], x[2]))
        (output / f"{key}.json").write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")

    manifest = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_URL,
        "license": "CC-BY-4.0",
        "citation": "Messager et al. (2016), HydroLAKES v1.0, HydroSHEDS",
        "derived_subset": "Canada plus U.S. lakes north of 40N",
        "min_area_km2": min_area,
        "shard_size_degrees": shard_size,
        "fields": FIELDS,
        "record_count": kept,
        "shard_count": len(shards),
        "country_counts": dict(sorted(countries.items())),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="north-america/data/hydrolakes")
    p.add_argument("--min-area", type=float, default=0.5)
    p.add_argument("--shard-size", type=int, default=2)
    args = p.parse_args()
    build(Path(args.output), args.min_area, args.shard_size)


if __name__ == "__main__":
    main()
