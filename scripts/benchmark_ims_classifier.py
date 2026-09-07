#!/usr/bin/env python3
"""Held-out benchmark for NOAA/USNIC IMS as a near-breakup lake-state signal.

Purpose: decide whether IMS may become an observational layer inside the final ice-out
window. The classifier threshold is selected on training lakes only and evaluated on
untouched lakes. False "open" calls are penalized because they are the harmful failure.

This benchmark does NOT modify the production model.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import os
import re
import statistics
import tempfile
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.windows import Window

CAL = Path('north-america/data/ice-history/nsidc-calibration.json')
OUT = Path('north-america/data/satellite/ims-classifier-benchmark.json')
RAW = 'https://noaadata.apps.nsidc.org/NOAA/G01377/liag_freeze_thaw_table.csv'
IMS = 'https://noaadata.apps.nsidc.org/NOAA/G02156/GIS/1km'

START_YEAR = 2014
MAX_LAKES = 14
YEARS_PER_LAKE = 3
MIN_AREA_KM2 = 20
MIN_USABLE_PIXELS = 8
OFFSETS = [-7, -5, -3, -1, 0, 1, 3, 5, 7]
THRESHOLDS = [0.0, 0.05, 0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90]

os.environ.setdefault('GDAL_DISABLE_READDIR_ON_OPEN', 'EMPTY_DIR')
os.environ.setdefault('CPL_VSIL_CURL_ALLOWED_EXTENSIONS', '.tif,.tiff,.gz')
os.environ.setdefault('GDAL_HTTP_MULTIRANGE', 'YES')
os.environ.setdefault('GDAL_HTTP_MERGE_CONSECUTIVE_RANGES', 'YES')

_year_files: dict[int, list[str]] = {}

def load_events():
    req = urllib.request.Request(RAW, headers={'User-Agent': 'chrisizworski-ice-out/1.0'})
    raw = urllib.request.urlopen(req, timeout=90).read().decode('utf-8-sig')
    by = defaultdict(lambda: defaultdict(list))
    for r in csv.DictReader(io.StringIO(raw)):
        if r.get('lakeorriver', '').strip().upper() != 'L':
            continue
        try:
            y = int(r['iceoff_year'])
            d = dt.date(y, int(r['iceoff_month']), int(r['iceoff_day']))
        except Exception:
            continue
        by[r['lakecode'].strip()][y].append(d)
    # If a source has duplicate same-year observations, use earliest reported breakup.
    return {k: {y: min(ds) for y, ds in yrs.items()} for k, yrs in by.items()}

def candidate_lakes(cal, ev):
    out = []
    for h in cal['lakes']:
        area = h.get('surface_area_km2')
        years = sorted((y for y in ev.get(h['lakecode'], {}) if y >= START_YEAR), reverse=True)
        if area and float(area) >= MIN_AREA_KM2 and years:
            out.append((len(years), float(area), h, years[:YEARS_PER_LAKE]))
    out.sort(key=lambda z: (-z[0], -z[1]))
    return out[:MAX_LAKES]

def year_files(year: int):
    if year in _year_files:
        return _year_files[year]
    base = f'{IMS}/{year}/'
    req = urllib.request.Request(base, headers={'User-Agent': 'chrisizworski-ice-out/1.0'})
    with urllib.request.urlopen(req, timeout=90) as r:
        html = r.read().decode('utf-8', 'replace')
    hrefs = sorted(set(re.findall(r'href=["\']([^"\']+)["\']', html, re.I)))
    names = [n for n in hrefs if re.search(r'\.(?:tif|tiff)(?:\.gz)?$', n, re.I)]
    _year_files[year] = names
    print('IMS index', year, 'GeoTIFF-like', len(names))
    return names

def ims_url(d: dt.date):
    token = f'ims{d.year}{d.timetuple().tm_yday:03d}'
    c = [n for n in year_files(d.year) if token.lower() in n.lower() and '1km' in n.lower()]
    if not c:
        raise FileNotFoundError(f'No IMS 1-km GeoTIFF for {d.isoformat()}')
    c.sort(key=lambda n: ('00utc' in n.lower(), n.lower()), reverse=True)
    name = c[0]
    return name if name.startswith('http') else f'{IMS}/{d.year}/{name.lstrip("/")}'

def sample_dataset(ds, lat: float, lon: float, radius_px: int = 4):
    tr = Transformer.from_crs('EPSG:4326', ds.crs, always_xy=True)
    x, y = tr.transform(lon, lat)
    row, col = ds.index(x, y)
    r = radius_px
    c0, r0 = max(0, col-r), max(0, row-r)
    c1, r1 = min(ds.width, col+r+1), min(ds.height, row+r+1)
    a = ds.read(1, window=Window(c0, r0, c1-c0, r1-r0))
    water = int(np.sum(a == 1)); ice = int(np.sum(a == 3))
    land = int(np.sum(a == 2)); snow = int(np.sum(a == 4))
    usable = water + ice
    return {
        'water_pixels': water, 'ice_pixels': ice, 'land_pixels': land,
        'snow_pixels': snow, 'usable_water_ice_pixels': usable,
        'ice_fraction': (ice / usable) if usable else None,
    }

def deterministic_test_lake(code: str):
    # ~25% of lakes untouched during threshold selection.
    return int(hashlib.sha1(code.encode()).hexdigest()[:8], 16) % 4 == 0

def hist_open_probability(prior_dates, sample_date):
    if len(prior_dates) < 8:
        return None
    target_doy = sample_date.timetuple().tm_yday
    vals = [d.timetuple().tm_yday for d in prior_dates]
    # Same lightly smoothed empirical CDF family used by the production direct-history model.
    def sigmoid(x):
        x = max(-60.0, min(60.0, x))
        return 1.0 / (1.0 + math.exp(-x))
    return sum(sigmoid((target_doy-v)/3.0) for v in vals) / len(vals)

def metrics(rows, threshold=None, use_history=False):
    # offset 0 is reported separately because daily analyst timing and local ice-out
    # definitions can differ within a day. Classifier gate uses strict before/after days.
    usable = [r for r in rows if r['offset'] != 0 and r.get('ice_fraction') is not None]
    tp=tn=fp=fn=0; brier=[]
    for r in usable:
        truth = 1 if r['offset'] > 0 else 0
        if use_history:
            p = r.get('history_probability')
            if p is None: continue
            pred = 1 if p >= .5 else 0
        else:
            pred = 1 if r['ice_fraction'] <= threshold else 0
            # deterministic state call; Brier is still useful as a hard-state score.
            p = float(pred)
        brier.append((p-truth)**2)
        if truth and pred: tp += 1
        elif not truth and not pred: tn += 1
        elif not truth and pred: fp += 1
        else: fn += 1
    n=tp+tn+fp+fn
    tpr=tp/(tp+fn) if tp+fn else None
    tnr=tn/(tn+fp) if tn+fp else None
    bal=(tpr+tnr)/2 if tpr is not None and tnr is not None else None
    return {
        'n': n, 'accuracy': round((tp+tn)/n,4) if n else None,
        'balanced_accuracy': round(bal,4) if bal is not None else None,
        'open_sensitivity': round(tpr,4) if tpr is not None else None,
        'frozen_specificity': round(tnr,4) if tnr is not None else None,
        'false_open_rate': round(fp/(fp+tn),4) if fp+tn else None,
        'false_frozen_rate': round(fn/(fn+tp),4) if fn+tp else None,
        'brier_hard': round(statistics.mean(brier),4) if brier else None,
        'confusion': {'tp':tp,'tn':tn,'fp':fp,'fn':fn},
    }

def choose_threshold(train):
    scored=[]
    for th in THRESHOLDS:
        m=metrics(train, threshold=th)
        if not m['n'] or m['balanced_accuracy'] is None: continue
        false_open=m['false_open_rate'] if m['false_open_rate'] is not None else 1
        # Prefer thresholds satisfying <=8% false-open on training lakes. Then maximize
        # balanced accuracy; ties favor lower false-open and more conservative thresholds.
        safe = false_open <= .08
        score=(1 if safe else 0, m['balanced_accuracy'], -false_open, -th)
        scored.append((score,th,m))
    if not scored: raise RuntimeError('No usable threshold candidates')
    scored.sort(reverse=True)
    return scored[0][1], {str(th):m for _,th,m in scored}

cal=json.loads(CAL.read_text())
ev=load_events()
selected=candidate_lakes(cal,ev)
requests=[]
for _,area,h,years in selected:
    code=h['lakecode']
    for year in years:
        truth=ev[code][year]
        prior=[d for y,d in ev[code].items() if y < year]
        if len(prior) < 8: continue
        for off in OFFSETS:
            d=truth+dt.timedelta(days=off)
            requests.append({
                'lakecode':code,'lake':h['name'],'country':h['country'],
                'lat':float(h['lat']),'lon':float(h['lon']),'area_km2':area,
                'year':year,'iceout_date':truth.isoformat(),'offset':off,
                'sample_date':d,'history_probability':hist_open_probability(prior,d),
            })

# Group by date so each compressed daily IMS raster is opened only once and sampled for
# every requested lake on that day.
by_date=defaultdict(list)
for r in requests: by_date[r['sample_date']].append(r)
rows=[]; failures=[]
for d in sorted(by_date):
    try:
        url=ims_url(d)
        path='/vsigzip//vsicurl/'+url if url.lower().endswith('.gz') else '/vsicurl/'+url
        with rasterio.open(path) as ds:
            for r in by_date[d]:
                try:
                    s=sample_dataset(ds,r['lat'],r['lon'])
                    item={**r,**s,'sample_date':d.isoformat(),'url':url}
                    if item['usable_water_ice_pixels'] < MIN_USABLE_PIXELS:
                        item['ice_fraction']=None
                        item['quality_error']=f"only {item['usable_water_ice_pixels']} water/ice pixels"
                    rows.append(item)
                except Exception as e:
                    failures.append({'date':d.isoformat(),'lakecode':r['lakecode'],'error':str(e)[:300]})
    except Exception as e:
        failures.append({'date':d.isoformat(),'error':str(e)[:300],'affected_requests':len(by_date[d])})
        print('date failure',d,e)

train=[r for r in rows if not deterministic_test_lake(r['lakecode'])]
test=[r for r in rows if deterministic_test_lake(r['lakecode'])]
threshold,train_candidates=choose_threshold(train)
train_ims=metrics(train,threshold=threshold);test_ims=metrics(test,threshold=threshold)
train_hist=metrics(train,use_history=True);test_hist=metrics(test,use_history=True)

heldout_lakes=sorted(set(r['lakecode'] for r in test if r.get('ice_fraction') is not None))
train_lakes=sorted(set(r['lakecode'] for r in train if r.get('ice_fraction') is not None))
improvement=(test_ims['balanced_accuracy']-test_hist['balanced_accuracy']) if test_ims['balanced_accuracy'] is not None and test_hist['balanced_accuracy'] is not None else None
passes=bool(
    len(heldout_lakes)>=3 and test_ims['n']>=40 and
    test_ims['balanced_accuracy'] is not None and test_ims['balanced_accuracy']>=.80 and
    test_ims['false_open_rate'] is not None and test_ims['false_open_rate']<=.10 and
    improvement is not None and improvement>=.10
)

# At reported day 0, show how often IMS already calls open but do not use it in gate.
day0=[r for r in test if r['offset']==0 and r.get('ice_fraction') is not None]
day0_open=sum(r['ice_fraction']<=threshold for r in day0)

out={
    'version':1,
    'source':'NOAA/USNIC IMS G02156 1-km GeoTIFF',
    'truth_source':'NSIDC G01377 lake ice-out dates',
    'method':'9x9 IMS neighborhood; only class 1 water and class 3 ice pixels define ice fraction; threshold selected on training lakes; deterministic whole-lake 25% holdout; offset 0 excluded from gate.',
    'selection':{'start_year':START_YEAR,'max_lakes':MAX_LAKES,'years_per_lake':YEARS_PER_LAKE,'min_area_km2':MIN_AREA_KM2,'min_usable_water_ice_pixels':MIN_USABLE_PIXELS,'offsets_days':OFFSETS},
    'selected_lakes':[{'lakecode':h['lakecode'],'lake':h['name'],'area_km2':area,'years':years} for _,area,h,years in selected],
    'observations':len(rows),'failures':failures,
    'train_lakes':train_lakes,'heldout_lakes':heldout_lakes,
    'candidate_thresholds':train_candidates,'selected_ice_fraction_threshold':threshold,
    'train':{'ims':train_ims,'history_only':train_hist},
    'heldout':{'ims':test_ims,'history_only':test_hist,'balanced_accuracy_improvement':round(improvement,4) if improvement is not None else None},
    'reported_day_zero':{'n':len(day0),'ims_open_fraction':round(day0_open/len(day0),4) if day0 else None},
    'release_gate':{'minimum_heldout_lakes':3,'minimum_heldout_observations':40,'minimum_balanced_accuracy':.80,'maximum_false_open_rate':.10,'minimum_absolute_balanced_accuracy_improvement_vs_history':.10},
    'passes':passes,
    'deployment_rule':'If passes=true, proceed to a persistence/state-transition benchmark before production. Do not directly convert a single IMS snapshot into a user probability.',
}
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(out,indent=2,default=str),encoding='utf-8')
print(json.dumps({k:out[k] for k in ['selected_ice_fraction_threshold','train','heldout','reported_day_zero','passes']},indent=2))
