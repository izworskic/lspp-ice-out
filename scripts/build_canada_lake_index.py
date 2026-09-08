#!/usr/bin/env python3
"""Build a static Canadian lake-name index from NRCan's weekly CGNDB CSV.

The runtime must not depend on GeoGratis availability for each search. This
builder downloads the authoritative national Canadian Geographical Names data,
keeps lake features, and emits compact prefix shards matching the U.S. index:
[id, name, province_code, province_name, country, lat, lon, feature_class, location]
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SOURCES = [
    "https://ftp.maps.canada.ca/pub/nrcan_rncan/vector/geobase_cgn_toponyme/prov_csv_eng/cgn_canada_csv_eng.zip",
    "https://ftp.cartes.canada.ca/pub/nrcan_rncan/vector/geobase_cgn_toponyme/prov_csv_eng/cgn_canada_csv_eng.zip",
]
OUT = Path("north-america/data/lake-index-ca")
UA = "ChrisIzworski-LakeIceOut/1.0 (+https://chrisizworski.com)"
GENERIC_WORDS = {"lake", "lac", "reservoir", "pond", "flowage"}
PROVINCES = {
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "ON": "Ontario",
    "PE": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "YT": "Yukon",
}
NUMERIC_PROVINCES = {
    "10": "NL", "11": "PE", "12": "NS", "13": "NB", "24": "QC",
    "35": "ON", "46": "MB", "47": "SK", "48": "AB", "59": "BC",
    "60": "YT", "61": "NT", "62": "NU",
}
PROVINCE_BY_NAME = {v.lower(): k for k, v in PROVINCES.items()}
PROVINCE_BY_NAME.update({
    "quebec": "QC", "québec": "QC", "newfoundland & labrador": "NL",
    "nwt": "NT", "northwest territory": "NT", "pei": "PE",
})


def norm(value):
    s = unicodedata.normalize("NFD", str(value or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def core(value):
    return " ".join(t for t in norm(value).split() if t not in GENERIC_WORDS)


def shard(value):
    c = re.sub(r"[^a-z0-9]", "", core(value) or norm(value))
    return (c[:2] if len(c) >= 2 else (c + "_")[:2]) or "__"


def clean_header(value):
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").strip().upper()).strip("_")


def normalized_row(row):
    return {clean_header(k): str(v or "").strip() for k, v in row.items() if k is not None}


def get(row, *names):
    for name in names:
        value = row.get(clean_header(name), "")
        if value:
            return value
    return ""


def as_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def province_code(value):
    raw = str(value or "").strip()
    if raw.upper() in PROVINCES:
        return raw.upper()
    if raw in NUMERIC_PROVINCES:
        return NUMERIC_PROVINCES[raw]
    return PROVINCE_BY_NAME.get(raw.lower()) or PROVINCE_BY_NAME.get(norm(raw), "")


def download():
    failures = []
    for source in SOURCES:
        try:
            req = urllib.request.Request(source, headers={"User-Agent": UA, "Accept": "application/zip,*/*"})
            with urllib.request.urlopen(req, timeout=240) as response:
                blob = response.read()
            if len(blob) < 1_000_000:
                raise RuntimeError(f"download unexpectedly small ({len(blob)} bytes)")
            print("Downloaded CGNDB:", source, "bytes:", len(blob))
            return source, blob
        except Exception as exc:
            failures.append(f"{source}: {exc}")
            print("CGNDB source failed:", failures[-1])
    raise RuntimeError("All CGNDB sources failed: " + " | ".join(failures))


def choose_csv(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        members = [m for m in archive.infolist() if m.filename.lower().endswith(".csv") and not m.is_dir()]
        if not members:
            raise RuntimeError("CGNDB ZIP contains no CSV")
        # National packages can include supporting CSVs; the toponym table is the largest.
        member = max(members, key=lambda m: m.file_size)
        raw = archive.read(member).decode("utf-8-sig", errors="replace")
    print("CGNDB CSV member:", member.filename, "bytes:", member.file_size)
    return member.filename, raw


def make_reader(raw):
    sample = raw[:50000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;|\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    print("CGNDB headers:", reader.fieldnames)
    return reader


def is_lake(row):
    concise = get(row, "CONCISE", "CONCISE_CODE", "CONCISE_TERM", "FEATURE_TYPE")
    generic = get(row, "GENERIC", "GENERIC_TERM", "FEATURE_CLASS")
    c, g = norm(concise), norm(generic)
    # CGNDB's concise code is the stable lake feature classification. Category
    # (O/P/M) describes naming/feature context and MUST NOT be used to exclude lakes.
    return str(concise).strip().upper() == "LAKE" or c.startswith("lake") or g in {
        "lake", "lac", "reservoir", "reservoirs", "lakes"
    }


def name_id_pairs(row):
    # Standard CGNDB national CSV is one name per row.
    base_name = get(row, "GEONAME", "GEOGRAPHICAL_NAME", "NAME", "OFFICIAL_NAME")
    base_id = get(row, "CGNDB_ID", "CGNDB_KEY", "KEY", "ID", "IDENTIFIER")
    if base_name:
        return [(base_id, base_name)]

    # Some CGNDB-derived exports are wide (EN/FR/Indigenous columns). Accept
    # those too so the builder survives source-format changes.
    pairs = []
    feature_id = get(row, "FEATURE_ID", "TOPONYMIC_FEATURE_ID")
    for suffix in ("EN", "FR", "IN"):
        name = get(row, f"GEONAME_{suffix}", f"GEOGRAPHICAL_NAME_{suffix}")
        if not name:
            continue
        key = get(row, f"CGNDB_ID_{suffix}", f"CGNDB_KEY_{suffix}") or feature_id
        pairs.append((f"{key}-{suffix.lower()}" if key else "", name))
    return pairs


def main():
    source, blob = download()
    member, raw = choose_csv(blob)
    reader = make_reader(raw)

    rows = []
    concise_counts = Counter()
    province_counts = Counter()
    missing = Counter()
    seen = set()

    for original in reader:
        row = normalized_row(original)
        concise_counts[get(row, "CONCISE", "CONCISE_CODE", "CONCISE_TERM", "FEATURE_TYPE")] += 1
        if not is_lake(row):
            continue

        pc = province_code(get(row, "PROV_TERR", "PROVINCE_TERRITORY", "PROVINCE", "PROVINCE_NAME"))
        lat = as_float(get(row, "LATITUDE", "LATITUDE_DECIMAL", "LAT"))
        lon = as_float(get(row, "LONGITUDE", "LONGITUDE_DECIMAL", "LON", "LONG"))
        location = get(row, "LOCATION", "DISTRICT", "LOCATION_NAME")
        if not pc:
            missing["province"] += 1
            continue
        if lat is None or lon is None:
            missing["coordinates"] += 1
            continue

        pairs = name_id_pairs(row)
        if not pairs:
            missing["name"] += 1
            continue
        for key, name in pairs:
            if not key:
                # Stable fallback only if the source omitted a name-level ID.
                key = get(row, "FEATURE_ID", "TOPONYMIC_FEATURE_ID") or f"{pc}-{lat:.6f}-{lon:.6f}-{norm(name)}"
            identity = (str(key), norm(name), pc, round(lat, 6), round(lon, 6))
            if identity in seen:
                continue
            seen.add(identity)
            province_counts[pc] += 1
            rows.append([
                f"cgndb-{key}", name, pc, PROVINCES[pc], "CA",
                round(lat, 6), round(lon, 6), "Lake", location,
            ])

    print("Top concise codes:", concise_counts.most_common(20))
    print("Canadian lake counts by province:", sorted(province_counts.items()))
    print("Skipped lake rows:", dict(missing))
    print("Canadian lake/name records:", len(rows))

    # These gates protect both continental coverage and known major-lake cases.
    if len(rows) < 25_000:
        raise AssertionError(f"Canadian lake index unexpectedly small: {len(rows)}")
    checks = {
        "lake nipigon on": any(norm(r[1]) == "lake nipigon" and r[2] == "ON" for r in rows),
        "lake winnipeg mb": any(norm(r[1]) == "lake winnipeg" and r[2] == "MB" for r in rows),
        "great bear lake nt": any(norm(r[1]) == "great bear lake" and r[2] == "NT" for r in rows),
    }
    print("Canadian release checks:", checks)
    if not all(checks.values()):
        raise AssertionError(f"Required Canadian lake missing: {checks}")

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    shards = defaultdict(list)
    for row in rows:
        shards[shard(row[1])].append(row)
    for key, values in shards.items():
        values.sort(key=lambda r: (norm(r[1]), r[2], r[0]))
        (OUT / f"{key}.json").write_text(
            json.dumps(values, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    manifest = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": len(rows),
        "ca_records": len(rows),
        "shards": len(shards),
        "source": source,
        "source_member": member,
        "source_name": "Natural Resources Canada Canadian Geographical Names Database (CGNDB)",
        "record_schema": ["id", "name", "region_code", "region_name", "country", "lat", "lon", "feature_class", "location"],
        "release_checks": checks,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Wrote Canadian shards:", len(shards))


if __name__ == "__main__":
    main()
