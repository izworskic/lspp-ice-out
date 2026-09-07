#!/usr/bin/env python3
from __future__ import annotations

import csv, json, math, statistics, urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

BASE='https://noaadata.apps.nsidc.org/NOAA/G01377/'
FREEZE='liag_freeze_thaw_table.csv'
PHYS='liag_physical_character_table.csv'
OUT=Path('north-america/data/ice-history/nsidc-calibration.json')
NA_COUNTRIES={'USA','UNITED STATES','UNITED STATES OF AMERICA','CANADA'}


def download_csv(name):
    req=urllib.request.Request(BASE+name,headers={'User-Agent':'ChrisIzworski-IceOut/1.0'})
    with urllib.request.urlopen(req,timeout=120) as r:
        text=r.read().decode('utf-8-sig','replace')
    return list(csv.DictReader(text.splitlines()))


def num(v):
    try:
        x=float(v)
        return None if not math.isfinite(x) or x<=-900 else x
    except (TypeError,ValueError):
        return None


def clim_doy(month,day):
    try:return date(2001,int(month),int(day)).timetuple().tm_yday
    except Exception:return None


def percentile(xs,p):
    if not xs:return None
    ys=sorted(xs); pos=(len(ys)-1)*p; lo=math.floor(pos); hi=math.ceil(pos)
    if lo==hi:return ys[lo]
    return ys[lo]*(hi-pos)+ys[hi]*(pos-lo)


def slope_days_decade(points):
    if len(points)<15:return None
    xs=[x for x,_ in points];ys=[y for _,y in points]
    xm=sum(xs)/len(xs);ym=sum(ys)/len(ys)
    den=sum((x-xm)**2 for x in xs)
    if not den:return None
    slope=sum((x-xm)*(y-ym) for x,y in points)/den
    return slope*10

phys_rows=download_csv(PHYS)
phys={r['lakecode'].strip():r for r in phys_rows if r.get('lakecode')}
records=defaultdict(list)
meta={}
for r in download_csv(FREEZE):
    if (r.get('lakeorriver') or '').strip().upper()!='L':continue
    country=(r.get('country') or '').strip().upper()
    if country not in NA_COUNTRIES:continue
    d=clim_doy(r.get('iceoff_month'),r.get('iceoff_day'))
    y=num(r.get('iceoff_year'))
    lat=num(r.get('latitude'));lon=num(r.get('longitude'))
    if d is None or y is None or lat is None or lon is None:continue
    y=int(y)
    if y<1800 or y>datetime.now().year:continue
    code=(r.get('lakecode') or '').strip();
    if not code:continue
    records[code].append((y,d))
    meta[code]={'name':(r.get('lakename') or code).strip(),'country':country,'lat':lat,'lon':lon}

out=[]
for code,pts in records.items():
    pts=sorted(set(pts)); modern=[p for p in pts if p[0]>=1950]
    use=modern if len(modern)>=10 else pts
    if len(use)<5:continue
    days=[d for _,d in use]; pr=phys.get(code,{})
    lat=num(pr.get('lat_decimal')) or meta[code]['lat'];lon=num(pr.get('lon_decimal')) or meta[code]['lon']
    row={
        'lakecode':code,'name':meta[code]['name'],'country':meta[code]['country'],
        'state':(pr.get('state') or '').strip(),'lat':lat,'lon':lon,
        'records':len(use),'records_all':len(pts),'first_year':use[0][0],'last_year':use[-1][0],
        'median_doy':round(statistics.median(days),1),'p10_doy':round(percentile(days,.1),1),'p90_doy':round(percentile(days,.9),1),
        'earliest_doy':min(days),'latest_doy':max(days),'trend_days_decade':None,
        'elevation_m':num(pr.get('elevation')),'mean_depth_m':num(pr.get('mean_depth')),'surface_area_km2':num(pr.get('surface_area'))
    }
    trend=slope_days_decade(use)
    if trend is not None:row['trend_days_decade']=round(trend,2)
    out.append(row)

out.sort(key=lambda x:(x['country'],x['name'],x['lakecode']))
manifest={
    'version':1,'generated_at':datetime.now(timezone.utc).isoformat(),'source':'NSIDC G01377',
    'doi':'10.7265/N5W66HP8','source_url':BASE,'definition_note':'Observation definitions vary by contributor; use as historical calibration, not a uniform operational ice-out definition.',
    'modern_period_start':1950,'lake_count':len(out),'record_count':sum(x['records'] for x in out),
    'lakes':out
}
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(manifest,separators=(',',':')),encoding='utf-8')
print(json.dumps({'lake_count':manifest['lake_count'],'record_count':manifest['record_count'],'sample':out[:5]},indent=2))
