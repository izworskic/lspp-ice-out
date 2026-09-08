#!/usr/bin/env python3
"""Build a static Canadian lake-name index from NRCan CGNDB.

Uses the authoritative Canadian Geographical Names feature service and writes
compact prefix shards with the same schema as the U.S. GNIS lake index:
[id, name, province_code, province_name, country, lat, lon, feature_class, location]
"""
from __future__ import annotations
import json, re, time, unicodedata, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SERVICE = "https://maps-cartes.services.geo.ca/server_serveur/rest/services/NRCan/canadian_geographical_names_en/MapServer/0"
OUT = Path("north-america/data/lake-index-ca")
UA = "ChrisIzworski-LakeIceOut/1.0 (+https://chrisizworski.com)"
GENERIC = {"lake","lac","reservoir","pond","flowage"}
PROVINCES = {
    "AB":"Alberta","BC":"British Columbia","MB":"Manitoba","NB":"New Brunswick",
    "NL":"Newfoundland and Labrador","NS":"Nova Scotia","NT":"Northwest Territories",
    "NU":"Nunavut","ON":"Ontario","PE":"Prince Edward Island","QC":"Quebec",
    "SK":"Saskatchewan","YT":"Yukon"
}
PROVINCE_BY_NAME = {v.lower():k for k,v in PROVINCES.items()}
PROVINCE_BY_NAME.update({"quebec":"QC","québec":"QC","newfoundland & labrador":"NL","nwt":"NT"})

def norm(v):
    s=unicodedata.normalize("NFD",str(v or ""))
    s="".join(c for c in s if unicodedata.category(c)!="Mn")
    return re.sub(r"[^a-z0-9]+"," ",s.lower()).strip()

def core(v): return " ".join(t for t in norm(v).split() if t not in GENERIC)
def shard(v):
    c=re.sub(r"[^a-z0-9]","",core(v) or norm(v))
    return (c[:2] if len(c)>=2 else (c+"_")[:2]) or "__"
def province_code(v):
    raw=str(v or "").strip()
    if raw.upper() in PROVINCES:return raw.upper()
    return PROVINCE_BY_NAME.get(raw.lower()) or PROVINCE_BY_NAME.get(norm(raw),"")
def get_json(url, params=None, timeout=120):
    if params: url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        data=json.loads(r.read().decode("utf-8"))
    if isinstance(data,dict) and data.get("error"): raise RuntimeError(data["error"])
    return data

def field_map(meta):
    out={}
    for f in meta.get("fields",[]):
        name=f.get("name",""); alias=f.get("alias","")
        out[norm(name)]=name; out[norm(alias)]=name
    return out

def find_field(fm,*needles):
    for needle in needles:
        n=norm(needle)
        if n in fm:return fm[n]
    for k,v in fm.items():
        if any(norm(x) in k for x in needles):return v
    return ""

def attr(attrs, field): return attrs.get(field) if field else None

def main():
    meta=get_json(SERVICE,{"f":"json"})
    fm=field_map(meta)
    print("CGNDB service fields:",[(f.get("name"),f.get("alias")) for f in meta.get("fields",[])])
    name_f=find_field(fm,"geographical name","geoname","name")
    key_f=find_field(fm,"cgndb key","key","unique id","identifier")
    province_f=find_field(fm,"province territory","province - territory","province")
    concise_f=find_field(fm,"concise code","concise term","concise")
    generic_f=find_field(fm,"generic term","generic")
    location_f=find_field(fm,"location")
    oid_f=meta.get("objectIdField") or find_field(fm,"objectid")
    print("Resolved fields:",dict(name=name_f,key=key_f,province=province_f,concise=concise_f,generic=generic_f,location=location_f,oid=oid_f))
    if not (name_f and key_f and province_f and oid_f): raise AssertionError("Required CGNDB fields not resolved")

    # Fetch authoritative feature IDs once, then page in deterministic batches.
    ids=get_json(SERVICE+"/query",{"where":"1=1","returnIdsOnly":"true","f":"json"}).get("objectIds") or []
    if len(ids)<100000: raise AssertionError(f"CGNDB object id set unexpectedly small: {len(ids)}")
    print("CGNDB total object ids:",len(ids))
    batch_size=1000
    rows=[]; concise_counts=Counter(); generic_counts=Counter(); province_counts=Counter()
    for i in range(0,len(ids),batch_size):
        batch=ids[i:i+batch_size]
        data=get_json(SERVICE+"/query",{
            "objectIds":",".join(map(str,batch)),"outFields":"*","returnGeometry":"true",
            "outSR":"4326","f":"json"
        },timeout=180)
        for ft in data.get("features",[]):
            a=ft.get("attributes") or {}; g=ft.get("geometry") or {}
            concise=str(attr(a,concise_f) or ""); generic=str(attr(a,generic_f) or "")
            concise_counts[concise]+=1; generic_counts[generic]+=1
            c=norm(concise); ge=norm(generic)
            lake = str(concise).strip().upper()=="LAKE" or c.startswith("lake") or ge in {"lake","lac","reservoir","reservoirs","lakes"}
            if not lake: continue
            name=str(attr(a,name_f) or "").strip(); key=str(attr(a,key_f) or "").strip()
            pc=province_code(attr(a,province_f)); lat=g.get("y"); lon=g.get("x")
            location=str(attr(a,location_f) or "").strip()
            try: lat=float(lat); lon=float(lon)
            except: continue
            if not (name and key and pc): continue
            province_counts[pc]+=1
            rows.append([f"cgndb-{key}",name,pc,PROVINCES[pc],"CA",round(lat,6),round(lon,6),"Lake",location])
        if i and i%25000==0: print("processed",i,"objects; lakes",len(rows))
        time.sleep(.02)

    print("Top concise:",concise_counts.most_common(25))
    print("Top generic:",generic_counts.most_common(25))
    print("Lake counts by province:",sorted(province_counts.items()))
    if len(rows)<25000: raise AssertionError(f"Canadian lake index unexpectedly small: {len(rows)}")
    checks={
        "lake nipigon on":any(norm(r[1])=="lake nipigon" and r[2]=="ON" for r in rows),
        "lake winnipeg mb":any(norm(r[1])=="lake winnipeg" and r[2]=="MB" for r in rows),
        "great bear lake nt":any(norm(r[1])=="great bear lake" and r[2]=="NT" for r in rows),
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
        "version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"records":len(rows),"ca_records":len(rows),
        "shards":len(shards),"source":SERVICE,"source_name":"Natural Resources Canada Canadian Geographical Names Database (CGNDB)",
        "record_schema":["id","name","region_code","region_name","country","lat","lon","feature_class","location"]
    }
    (OUT/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    print("Canadian lake records:",len(rows),"shards:",len(shards))

if __name__=="__main__":main()
