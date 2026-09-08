#!/usr/bin/env python3
"""Build a static Canadian lake-name index from NRCan's weekly CGNDB national CSV.

Output records use the same compact schema as the U.S. index:
[id, name, province_code, province_name, country, lat, lon, feature_class, location]
"""
from __future__ import annotations
import csv, io, json, re, unicodedata, urllib.request, zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SOURCE = "https://www.download-telecharger.services.geo.ca/pub/nrcan_rncan/vector/geobase_cgn_toponyme/prov_csv_eng/cgn_canada_csv_eng.zip"
OUT = Path("north-america/data/lake-index-ca")
UA = "ChrisIzworski-LakeIceOut/1.0 (+https://chrisizworski.com)"
GENERIC = {"lake", "lac", "reservoir", "pond", "flowage"}
PROVINCES = {
    "AB":"Alberta","BC":"British Columbia","MB":"Manitoba","NB":"New Brunswick",
    "NL":"Newfoundland and Labrador","NS":"Nova Scotia","NT":"Northwest Territories",
    "NU":"Nunavut","ON":"Ontario","PE":"Prince Edward Island","QC":"Quebec",
    "SK":"Saskatchewan","YT":"Yukon"
}
PROVINCE_BY_NAME = {v.lower(): k for k,v in PROVINCES.items()}
PROVINCE_BY_NAME.update({"québec":"QC","quebec":"QC","newfoundland & labrador":"NL","nwt":"NT"})


def norm(v):
    s=unicodedata.normalize("NFD", str(v or ""))
    s="".join(c for c in s if unicodedata.category(c)!="Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def core(v): return " ".join(t for t in norm(v).split() if t not in GENERIC)
def shard(v):
    c=re.sub(r"[^a-z0-9]", "", core(v) or norm(v))
    return (c[:2] if len(c)>=2 else (c+"_")[:2]) or "__"
def pick(row,*names):
    d={norm(k):str(v or "").strip() for k,v in row.items()}
    for n in names:
        x=d.get(norm(n),"")
        if x: return x
    return ""
def f(v):
    try: return float(str(v).strip())
    except: return None

def province_code(value):
    raw=str(value or "").strip()
    if raw.upper() in PROVINCES: return raw.upper()
    return PROVINCE_BY_NAME.get(raw.lower()) or PROVINCE_BY_NAME.get(norm(raw),"")

def is_lake(row):
    concise=pick(row,"Concise Code","ConciseCode","Concise Term","ConciseTerm","Feature Type","FeatureType")
    generic=pick(row,"Generic Term","GenericTerm","Generic","Feature Class","FeatureClass")
    c=norm(concise); g=norm(generic)
    if c.startswith("lake") or c=="lake" or "lake lake" in c: return True
    if g in {"lake","lac","reservoir","réservoir","reservoirs","lakes"}: return True
    # CGNDB concise values commonly carry LAKE as the compact code.
    if str(concise).strip().upper()=="LAKE": return True
    return False

def main():
    req=urllib.request.Request(SOURCE,headers={"User-Agent":UA})
    with urllib.request.urlopen(req,timeout=240) as r: blob=r.read()
    print("Downloaded CGNDB bytes:",len(blob))
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        members=[m for m in z.infolist() if m.filename.lower().endswith(".csv")]
        if not members: raise RuntimeError("CGNDB ZIP has no CSV")
        member=max(members,key=lambda m:m.file_size)
        raw=z.read(member).decode("utf-8-sig",errors="replace")
    sample=raw[:20000]
    try: dialect=csv.Sniffer().sniff(sample,delimiters=",;|\t")
    except csv.Error: dialect=csv.excel
    reader=csv.DictReader(io.StringIO(raw),dialect=dialect)
    print("CGNDB member:",member.filename,"bytes:",member.file_size)
    print("CGNDB fields:",reader.fieldnames)
    rows=[]; concise_counts=Counter(); generic_counts=Counter(); province_counts=Counter()
    for r in reader:
        concise=pick(r,"Concise Code","ConciseCode","Concise Term","ConciseTerm","Feature Type","FeatureType")
        generic=pick(r,"Generic Term","GenericTerm","Generic","Feature Class","FeatureClass")
        concise_counts[concise]+=1; generic_counts[generic]+=1
        if not is_lake(r): continue
        name=pick(r,"Geographical Name","GeographicalName","Geoname","Name","Official Name","OfficialName")
        key=pick(r,"CGNDB Key","CGNDBKey","Key","Unique ID","UniqueID","Identifier","Id")
        province_raw=pick(r,"Province - Territory","Province/Territory","Province Territory","Province","Province Name","ProvinceName")
        pc=province_code(province_raw)
        lat=f(pick(r,"Latitude","Latitude Decimal","LatitudeDecimal","Lat"))
        lon=f(pick(r,"Longitude","Longitude Decimal","LongitudeDecimal","Long","Lon"))
        location=pick(r,"Location","Location Name","LocationName")
        if not (name and key and pc and lat is not None and lon is not None): continue
        province_counts[pc]+=1
        rows.append([f"cgndb-{key}",name,pc,PROVINCES[pc],"CA",round(lat,6),round(lon,6),"Lake",location])
    print("Top concise:",concise_counts.most_common(25))
    print("Top generic:",generic_counts.most_common(25))
    print("Lake counts by province:",sorted(province_counts.items()))
    if len(rows)<25000: raise AssertionError(f"Canadian lake index unexpectedly small: {len(rows)}")
    checks={
        "lake nipigon on": any(norm(r[1])=="lake nipigon" and r[2]=="ON" for r in rows),
        "lake winnipeg mb": any(norm(r[1])=="lake winnipeg" and r[2]=="MB" for r in rows),
        "great bear lake nt": any(norm(r[1])=="great bear lake" and r[2]=="NT" for r in rows),
    }
    print("Release checks:",checks)
    if not all(checks.values()): raise AssertionError(f"Canadian release lake missing: {checks}")
    OUT.mkdir(parents=True,exist_ok=True)
    for old in OUT.glob("*.json"): old.unlink()
    shards=defaultdict(list)
    for r in rows: shards[shard(r[1])].append(r)
    for k,vals in shards.items():
        vals.sort(key=lambda r:(norm(r[1]),r[2],r[0]))
        (OUT/f"{k}.json").write_text(json.dumps(vals,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    manifest={
        "version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"records":len(rows),
        "ca_records":len(rows),"shards":len(shards),"source":SOURCE,
        "source_name":"Natural Resources Canada Canadian Geographical Names Database (CGNDB)",
        "record_schema":["id","name","region_code","region_name","country","lat","lon","feature_class","location"]
    }
    (OUT/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    print("Canadian lake records:",len(rows),"shards:",len(shards))

if __name__=="__main__": main()
