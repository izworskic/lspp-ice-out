#!/usr/bin/env python3
"""Build a static U.S. lake-name database from the complete USGS GNIS national file.

The browser-facing output is sharded by the first two characters of a normalized
core lake name. Each record is a compact array:
[id, name, state_code, state_name, country, lat, lon, feature_class, county]
"""
from __future__ import annotations
import csv, io, json, re, unicodedata, urllib.request, zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SOURCE = "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/DomesticNames_National_Text.zip"
OUT = Path("north-america/data/lake-index")
UA = "ChrisIzworski-LakeIceOut/1.0 (+https://chrisizworski.com)"
GENERIC = {"lake","lac","reservoir","pond","flowage"}
STATE_NAMES = {
'AL':'Alabama','AK':'Alaska','AZ':'Arizona','AR':'Arkansas','CA':'California','CO':'Colorado','CT':'Connecticut','DE':'Delaware','FL':'Florida','GA':'Georgia','HI':'Hawaii','ID':'Idaho','IL':'Illinois','IN':'Indiana','IA':'Iowa','KS':'Kansas','KY':'Kentucky','LA':'Louisiana','ME':'Maine','MD':'Maryland','MA':'Massachusetts','MI':'Michigan','MN':'Minnesota','MS':'Mississippi','MO':'Missouri','MT':'Montana','NE':'Nebraska','NV':'Nevada','NH':'New Hampshire','NJ':'New Jersey','NM':'New Mexico','NY':'New York','NC':'North Carolina','ND':'North Dakota','OH':'Ohio','OK':'Oklahoma','OR':'Oregon','PA':'Pennsylvania','RI':'Rhode Island','SC':'South Carolina','SD':'South Dakota','TN':'Tennessee','TX':'Texas','UT':'Utah','VT':'Vermont','VA':'Virginia','WA':'Washington','WV':'West Virginia','WI':'Wisconsin','WY':'Wyoming','DC':'District of Columbia','PR':'Puerto Rico','VI':'U.S. Virgin Islands','GU':'Guam','MP':'Northern Mariana Islands','AS':'American Samoa'}

def norm(v):
    s=unicodedata.normalize('NFD',str(v or ''))
    s=''.join(c for c in s if unicodedata.category(c)!='Mn')
    return re.sub(r'[^a-z0-9]+',' ',s.lower()).strip()

def core(v): return ' '.join(t for t in norm(v).split() if t not in GENERIC)
def shard(v):
    c=re.sub(r'[^a-z0-9]','',core(v) or norm(v))
    return (c[:2] if len(c)>=2 else (c+'_')[:2]) or '__'
def pick(row,*names):
    d={str(k).strip().lower():str(v or '').strip() for k,v in row.items()}
    for n in names:
        if d.get(n.lower()): return d[n.lower()]
    return ''
def f(v):
    try: return float(v)
    except: return None

def main():
    req=urllib.request.Request(SOURCE,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=240) as r: blob=r.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        members=[x for x in z.infolist() if x.filename.lower().endswith(('.txt','.csv'))]
        if not members: raise RuntimeError('GNIS ZIP has no text data')
        print('GNIS text members:',[(x.filename,x.file_size) for x in members])
        # Prefer the DomesticNames table explicitly. National packages can include
        # additional text tables, and the largest member is not guaranteed to be it.
        domestic=[x for x in members if 'domesticnames' in x.filename.lower()]
        member=max(domestic or members,key=lambda x:x.file_size)
        raw=z.read(member).decode('utf-8-sig',errors='replace')
    header=raw.splitlines()[0]
    delim='|' if header.count('|')>=header.count(',') else ','
    reader=csv.DictReader(io.StringIO(raw),delimiter=delim)
    print('GNIS selected member:',member.filename,'bytes:',member.file_size)
    print('GNIS delimiter:',repr(delim))
    print('GNIS fields:',reader.fieldnames)
    rows=[]; classes=defaultdict(int)
    for r in reader:
        fc=pick(r,'feature_class','feature class','featureclass'); classes[fc]+=1
        if fc.lower() not in {'lake','reservoir'}: continue
        name=pick(r,'feature_name','feature name','gnis_name','featurename')
        fid=pick(r,'feature_id','gnis_id','gnisid','featureid')
        state=pick(r,'state_alpha','state alpha','statealpha').upper()
        county=pick(r,'county_name','county name','countyname')
        lat=f(pick(r,'prim_lat_dec','primary_lat_dec','primary latitude','primlatdec'))
        lon=f(pick(r,'prim_long_dec','primary_long_dec','primary longitude','primlongdec'))
        if not (name and fid and state and lat is not None and lon is not None): continue
        rows.append([f'gnis-{fid}',name,state,STATE_NAMES.get(state,state),'US',round(lat,6),round(lon,6),fc,county])
    print('Top feature classes:',sorted(classes.items(),key=lambda kv:kv[1],reverse=True)[:30])
    if len(rows)<10000: raise AssertionError(f'GNIS lake index unexpectedly small: {len(rows)}')
    black=[r for r in rows if r[2]=='MI' and norm(r[1])=='black lake']
    if not black: raise AssertionError('Release gate failed: Black Lake MI missing from complete GNIS ingest')
    OUT.mkdir(parents=True,exist_ok=True)
    shards=defaultdict(list)
    for r in rows: shards[shard(r[1])].append(r)
    for k,vals in shards.items():
        vals.sort(key=lambda r:(norm(r[1]),r[2],r[0]))
        (OUT/f'{k}.json').write_text(json.dumps(vals,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    manifest={'version':1,'generated_at':datetime.now(timezone.utc).isoformat(),'records':len(rows),'us_records':len(rows),'ca_records':0,'shards':len(shards),'source':SOURCE,'record_schema':['id','name','region_code','region_name','country','lat','lon','feature_class','county']}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('U.S. lake/reservoir records:',len(rows),'shards:',len(shards))
    print('Black Lake MI hits:',len(black))
    for r in black[:20]: print(r)

if __name__=='__main__': main()
