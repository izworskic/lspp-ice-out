#!/usr/bin/env python3
"""Probe NOAA/USNIC IMS 1-km ice classes around known NSIDC lake ice-out dates.

This is deliberately a signal-discovery probe, not a production algorithm. It uses large
lakes with recent observations, samples only IMS water/ice pixels (1=open water, 3=ice),
and asks whether ice fraction falls across the reported ice-out date.
"""
from __future__ import annotations
import csv, datetime as dt, io, json, math, os, re, statistics, urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.windows import Window

CAL=Path('north-america/data/ice-history/nsidc-calibration.json')
OUT=Path('north-america/data/satellite/ims-signal-probe.json')
RAW='https://noaadata.apps.nsidc.org/NOAA/G01377/liag_freeze_thaw_table.csv'
IMS='https://noaadata.apps.nsidc.org/NOAA/G02156/GIS/1km'
OFFSETS=[-7,-3,0,3,7]
MAX_LAKES=8
YEARS_PER_LAKE=2
MIN_AREA_KM2=20

os.environ.setdefault('GDAL_DISABLE_READDIR_ON_OPEN','EMPTY_DIR')
os.environ.setdefault('CPL_VSIL_CURL_ALLOWED_EXTENSIONS','.tif,.tiff')
os.environ.setdefault('GDAL_HTTP_MULTIRANGE','YES')
os.environ.setdefault('GDAL_HTTP_MERGE_CONSECUTIVE_RANGES','YES')

_year_files={}
def events():
    raw=urllib.request.urlopen(RAW,timeout=90).read().decode('utf-8-sig');by=defaultdict(lambda:defaultdict(list))
    for r in csv.DictReader(io.StringIO(raw)):
        if r.get('lakeorriver','').strip().upper()!='L':continue
        try:y=int(r['iceoff_year']);d=dt.date(y,int(r['iceoff_month']),int(r['iceoff_day']))
        except Exception:continue
        if y>=2014:by[r['lakecode'].strip()][y].append(d)
    return {k:{y:min(ds) for y,ds in yrs.items()} for k,yrs in by.items()}

def candidate_lakes(cal,ev):
    out=[]
    for h in cal['lakes']:
        area=h.get('surface_area_km2');yrs=sorted(ev.get(h['lakecode'],{}),reverse=True)
        if area and area>=MIN_AREA_KM2 and yrs:out.append((len(yrs),float(area),h,yrs[:YEARS_PER_LAKE]))
    out.sort(key=lambda z:(-z[0],-z[1]));return out[:MAX_LAKES]

def year_files(year):
    if year in _year_files:return _year_files[year]
    base=f'{IMS}/{year}/';req=urllib.request.Request(base,headers={'User-Agent':'chrisizworski-ice-out/1.0'})
    with urllib.request.urlopen(req,timeout=90) as r:html=r.read().decode('utf-8','replace')
    names=sorted(set(re.findall(r'href=["\']([^"\']+\.(?:tif|tiff))["\']',html,re.I)))
    _year_files[year]=names;print('IMS index',year,len(names),'GeoTIFFs');return names

def ims_url(d):
    doy=d.timetuple().tm_yday;token=f'ims{d.year}{doy:03d}'
    candidates=[n for n in year_files(d.year) if token.lower() in n.lower() and '1km' in n.lower()]
    if not candidates:raise FileNotFoundError(f'No IMS 1-km GeoTIFF for {d.isoformat()}')
    # Prefer 00UTC when multiple products exist, then highest lexical version.
    candidates.sort(key=lambda n:('00utc' in n.lower(),n.lower()),reverse=True)
    name=candidates[0]
    return name if name.startswith('http') else f'{IMS}/{d.year}/{name.lstrip("/")}'

def sample(url,lat,lon,radius_px=4):
    with rasterio.open('/vsicurl/'+url) as ds:
        tr=Transformer.from_crs('EPSG:4326',ds.crs,always_xy=True);x,y=tr.transform(lon,lat);row,col=ds.index(x,y);r=radius_px
        c0=max(0,col-r);r0=max(0,row-r);c1=min(ds.width,col+r+1);r1=min(ds.height,row+r+1)
        a=ds.read(1,window=Window(c0,r0,c1-c0,r1-r0))
        water=int(np.sum(a==1));ice=int(np.sum(a==3));land=int(np.sum(a==2));snow=int(np.sum(a==4));usable=water+ice
        return {'water_pixels':water,'ice_pixels':ice,'land_pixels':land,'snow_pixels':snow,'usable_water_ice_pixels':usable,'ice_fraction':round(ice/usable,4) if usable else None,'shape':[int(a.shape[0]),int(a.shape[1])]}

cal=json.loads(CAL.read_text());ev=events();selected=candidate_lakes(cal,ev);cases=[]
for _,area,h,yrs in selected:
    for year in yrs:
        truth=ev[h['lakecode']][year];obs=[]
        for off in OFFSETS:
            d=truth+dt.timedelta(days=off)
            try:
                url=ims_url(d);r=sample(url,float(h['lat']),float(h['lon']));r.update({'offset_days':off,'date':d.isoformat(),'url':url})
            except Exception as e:r={'offset_days':off,'date':d.isoformat(),'error':str(e)[:500],'ice_fraction':None,'usable_water_ice_pixels':0}
            obs.append(r);print(h['name'],year,off,r.get('ice_fraction'),r.get('error',''))
        valid=[x for x in obs if x.get('ice_fraction') is not None];before=[x['ice_fraction'] for x in valid if x['offset_days']<0];after=[x['ice_fraction'] for x in valid if x['offset_days']>0]
        cases.append({'lakecode':h['lakecode'],'lake':h['name'],'country':h['country'],'lat':h['lat'],'lon':h['lon'],'area_km2':area,'year':year,'iceout_date':truth.isoformat(),'samples':obs,'median_pre_iceout_fraction':round(statistics.median(before),4) if before else None,'median_post_iceout_fraction':round(statistics.median(after),4) if after else None,'drop_pre_to_post':round(statistics.median(before)-statistics.median(after),4) if before and after else None})
usable=[c for c in cases if c['drop_pre_to_post'] is not None]
out={'version':2,'source':'NOAA/USNIC IMS G02156 1-km GeoTIFF','class_semantics':{'1':'open water/sea class','3':'ice','2':'land','4':'snow-covered land'},'method':'9x9-pixel neighborhood around NSIDC lake coordinate; fraction uses only IMS water+ice pixels; sampled -7,-3,0,+3,+7 days around reported ice-out; archive filename/version discovered from year index','candidate_rule':f'NSIDC lakes with area >= {MIN_AREA_KM2} km2 and observations since 2014','cases':cases,'summary':{'cases':len(cases),'usable_cases':len(usable),'positive_drop_fraction':round(sum(c['drop_pre_to_post']>0 for c in usable)/len(usable),4) if usable else None,'median_pre_fraction':round(statistics.median(c['median_pre_iceout_fraction'] for c in usable),4) if usable else None,'median_post_fraction':round(statistics.median(c['median_post_iceout_fraction'] for c in usable),4) if usable else None,'median_drop':round(statistics.median(c['drop_pre_to_post'] for c in usable),4) if usable else None},'gate':'Proceed to full IMS classifier backtest only if >=8 usable cases and >=70% show declining IMS ice fraction across reported ice-out.'}
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out['summary'],indent=2))
