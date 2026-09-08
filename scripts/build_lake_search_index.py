#!/usr/bin/env python3
"""Build a zero-runtime-cost North America lake search index.

Sources
- United States: USGS GNIS Domestic Names national TXT download.
- Canada: NRCan CGNDB GeoNames API, official current lake-like concise classes.

Output is sharded by normalized lake-name prefix so the browser only downloads the
small shard(s) relevant to a search. Records are compact arrays:
  [id, name, region_code, region_name, country, lat, lon, feature_class, county]
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("north-america/data/lake-index")
US_S3 = "https://prd-tnm.s3.amazonaws.com/"
US_PREFIX = "StagedProducts/GeographicNames/DomesticNames/"
CA_BASE = "https://geogratis.gc.ca/services/geoname/en"
UA = "ChrisIzworski-LakeIceOut/1.0 (+https://chrisizworski.com)"
GENERIC = {"lake", "lac", "reservoir", "pond", "flowage"}

US_STATE_NAMES = {
    'AL':'Alabama','AK':'Alaska','AZ':'Arizona','AR':'Arkansas','CA':'California','CO':'Colorado','CT':'Connecticut','DE':'Delaware','FL':'Florida','GA':'Georgia','HI':'Hawaii','ID':'Idaho','IL':'Illinois','IN':'Indiana','IA':'Iowa','KS':'Kansas','KY':'Kentucky','LA':'Louisiana','ME':'Maine','MD':'Maryland','MA':'Massachusetts','MI':'Michigan','MN':'Minnesota','MS':'Mississippi','MO':'Missouri','MT':'Montana','NE':'Nebraska','NV':'Nevada','NH':'New Hampshire','NJ':'New Jersey','NM':'New Mexico','NY':'New York','NC':'North Carolina','ND':'North Dakota','OH':'Ohio','OK':'Oklahoma','OR':'Oregon','PA':'Pennsylvania','RI':'Rhode Island','SC':'South Carolina','SD':'South Dakota','TN':'Tennessee','TX':'Texas','UT':'Utah','VT':'Vermont','VA':'Virginia','WA':'Washington','WV':'West Virginia','WI':'Wisconsin','WY':'Wyoming','DC':'District of Columbia','PR':'Puerto Rico','VI':'U.S. Virgin Islands','GU':'Guam','MP':'Northern Mariana Islands'
}


def http_bytes(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_json(url: str, timeout: int = 120):
    return json.loads(http_bytes(url, timeout).decode("utf-8-sig"))


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def core_name(s: str) -> str:
    return " ".join(t for t in norm(s).split() if t not in GENERIC)


def shard_key(name: str) -> str:
    c = re.sub(r"[^a-z0-9]", "", core_name(name) or norm(name))
    return (c[:2] if len(c) >= 2 else (c + "_")[:2]) or "__"


def as_float(v):
    try:
        x = float(v)
        return x if x == x else None
    except Exception:
        return None


def s3_keys(prefix: str):
    token = None
    while True:
        q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            q["continuation-token"] = token
        root = ET.fromstring(http_bytes(US_S3 + "?" + urllib.parse.urlencode(q)))
        ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
        for obj in root.findall("s:Contents", ns):
            key = obj.findtext("s:Key", default="", namespaces=ns)
            lm = obj.findtext("s:LastModified", default="", namespaces=ns)
            size = int(obj.findtext("s:Size", default="0", namespaces=ns) or 0)
            yield key, lm, size
        if root.findtext("s:IsTruncated", default="false", namespaces=ns) != "true":
            break
        token = root.findtext("s:NextContinuationToken", default="", namespaces=ns)
        if not token:
            break


def latest_us_national_zip() -> tuple[str, str]:
    rows = list(s3_keys(US_PREFIX))
    cands = []
    for key, lm, size in rows:
        base = key.rsplit("/", 1)[-1].lower()
        if not base.endswith(".zip"):
            continue
        if "national" not in base:
            continue
        if any(x in base for x in ("allstates", "federal", "fullmodel", "archive")):
            continue
        # DomesticNames national TXT products are far smaller than FullModel GPKG/GDB;
        # accept only files whose path remains inside DomesticNames.
        cands.append((lm, size, key))
    if not cands:
        print("S3 keys seen:", *[r[0] for r in rows[-30:]], sep="\n  ")
        raise RuntimeError("Could not discover GNIS DomesticNames national ZIP")
    cands.sort(reverse=True)
    key = cands[0][2]
    return US_S3 + urllib.parse.quote(key, safe="/"), key


def pick(row: dict, *names: str) -> str:
    low = {str(k).strip().lower(): v for k, v in row.items()}
    for n in names:
        if n.lower() in low and str(low[n.lower()] or "").strip():
            return str(low[n.lower()]).strip()
    return ""


def build_us() -> tuple[list[list], dict]:
    url, key = latest_us_national_zip()
    print("US GNIS source:", key)
    blob = http_bytes(url, timeout=240)
    z = zipfile.ZipFile(io.BytesIO(blob))
    txts = [i for i in z.infolist() if i.filename.lower().endswith((".txt", ".csv")) and not i.filename.startswith("__MACOSX/")]
    if not txts:
        raise RuntimeError("GNIS ZIP contains no text data file")
    info = max(txts, key=lambda x: x.file_size)
    print("US GNIS member:", info.filename, info.file_size)
    raw = z.read(info).decode("utf-8-sig", errors="replace")
    first = raw.splitlines()[0]
    delim = "|" if first.count("|") >= first.count(",") else ","
    reader = csv.DictReader(io.StringIO(raw), delimiter=delim)
    out = []
    classes = defaultdict(int)
    for row in reader:
        fc = pick(row, "feature_class", "feature class")
        classes[fc] += 1
        if fc.lower() not in {"lake", "reservoir"}:
            continue
        name = pick(row, "feature_name", "feature name", "gnis_name")
        fid = pick(row, "feature_id", "gnis_id", "gnisid")
        state = pick(row, "state_alpha", "state alpha")
        state_name = pick(row, "state_name", "state name") or US_STATE_NAMES.get(state.upper(), state)
        county = pick(row, "county_name", "county name")
        lat = as_float(pick(row, "primary_lat_dec", "prim_lat_dec", "primary_latitude", "primary latitude"))
        lon = as_float(pick(row, "primary_long_dec", "prim_long_dec", "primary_longitude", "primary longitude"))
        if not name or not fid or lat is None or lon is None:
            continue
        out.append([f"gnis-{fid}", name, state.upper(), state_name, "US", round(lat, 6), round(lon, 6), fc, county])
    meta = {"source_url": url, "source_key": key, "records": len(out), "classes_seen": dict(sorted(classes.items()))}
    return out, meta


def ca_items(obj):
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in ("items", "results", "geonames"):
            if isinstance(obj.get(k), list):
                return obj[k]
    return []


def ca_codes(path: str):
    return ca_items(http_json(f"{CA_BASE}/codes/{path}.json"))


def code_term(x):
    if isinstance(x, str):
        return x
    if not isinstance(x, dict):
        return ""
    return str(x.get("term") or x.get("code") or x.get("id") or x.get("value") or "")


def code_desc(x):
    if not isinstance(x, dict):
        return str(x)
    return str(x.get("description") or x.get("name") or x.get("label") or x.get("term") or "")


def get_nested(v, fallback=""):
    if isinstance(v, dict):
        return str(v.get("description") or v.get("term") or v.get("name") or fallback)
    return str(v or fallback)


def build_canada() -> tuple[list[list], dict]:
    concise = ca_codes("concise")
    provinces = ca_codes("province")
    selected = []
    for x in concise:
        term, desc = code_term(x), code_desc(x)
        d = norm(desc + " " + term)
        if any(w in d.split() for w in ("lake", "reservoir", "pond")):
            selected.append(term)
    if "LAKE" not in selected:
        selected.append("LAKE")
    selected = sorted(set(x for x in selected if x))
    print("Canada concise codes:", selected)

    province_name = {code_term(x): code_desc(x) for x in provinces if code_term(x)}
    rows = []
    seen = set()
    requests_count = 0
    # Query each lake-like feature class nationally in stable name order. The API
    # documents num<=1000 and skip pagination.
    for concise_code in selected:
        skip = 0
        while True:
            params = {
                "category": "O", "concise": concise_code, "num": "1000", "skip": str(skip),
                "sort-field": "name", "expand": "items.concise,items.province",
                "select": "items.concise.term,items.province.description"
            }
            obj = http_json(f"{CA_BASE}/geonames.json?{urllib.parse.urlencode(params)}")
            items = ca_items(obj)
            requests_count += 1
            if not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or item.get("cgndb_key") or item.get("id") or "")
                name = str(item.get("name") or item.get("geoname") or "").strip()
                lat = as_float(item.get("latitude", item.get("lat")))
                lon = as_float(item.get("longitude", item.get("lon")))
                prov_obj = item.get("province")
                prov_name = get_nested(prov_obj, "Canada")
                prov_code = ""
                if isinstance(prov_obj, dict):
                    prov_code = str(prov_obj.get("code") or prov_obj.get("term") or prov_obj.get("id") or "")
                if not prov_code:
                    prov_code = str(item.get("province_code") or item.get("provinceCode") or "")
                if not prov_name or prov_name == "Canada":
                    prov_name = province_name.get(prov_code, prov_name)
                feature = get_nested(item.get("concise"), concise_code)
                if not key or not name or lat is None or lon is None:
                    continue
                rid = f"cgndb-{key}"
                if rid in seen:
                    continue
                seen.add(rid)
                rows.append([rid, name, prov_code, prov_name, "CA", round(lat, 6), round(lon, 6), feature, ""])
            if len(items) < 1000:
                break
            skip += 1000
            if skip > 500000:
                raise RuntimeError(f"CGNDB runaway pagination for {concise_code}")
            time.sleep(0.04)
    meta = {"source": CA_BASE, "records": len(rows), "concise_codes": selected, "requests": requests_count}
    return rows, meta


def write_index(records: list[list], us_meta: dict, ca_meta: dict):
    if OUT.exists():
        for p in OUT.glob("*.json"):
            p.unlink()
    OUT.mkdir(parents=True, exist_ok=True)
    shards = defaultdict(list)
    for r in records:
        shards[shard_key(r[1])].append(r)
    for key, vals in shards.items():
        vals.sort(key=lambda r: (norm(r[1]), r[2], r[0]))
        (OUT / f"{key}.json").write_text(json.dumps(vals, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    manifest = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": len(records),
        "us_records": us_meta["records"],
        "ca_records": ca_meta["records"],
        "shards": len(shards),
        "shard_scheme": "first two alphanumeric characters of normalized core lake name",
        "record_schema": ["id", "name", "region_code", "region_name", "country", "lat", "lon", "feature_class", "county"],
        "sources": {"US": us_meta, "CA": ca_meta},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def validate(records: list[list], manifest: dict):
    assert manifest["records"] == len(records)
    assert manifest["us_records"] > 10000, manifest
    assert manifest["ca_records"] > 10000, manifest
    # Release-critical recall test from user report.
    hits = [r for r in records if r[4] == "US" and r[2] == "MI" and norm(r[1]) == "black lake"]
    if not hits:
        raise AssertionError("Release gate failed: GNIS database does not contain Black Lake, MI")
    print("Black Lake MI hits:")
    for r in hits[:20]:
        print(" ", r)
    print("manifest:", json.dumps({k: manifest[k] for k in ("records", "us_records", "ca_records", "shards")}, indent=2))


def main():
    us, us_meta = build_us()
    ca, ca_meta = build_canada()
    records = us + ca
    manifest = write_index(records, us_meta, ca_meta)
    validate(records, manifest)


if __name__ == "__main__":
    main()
