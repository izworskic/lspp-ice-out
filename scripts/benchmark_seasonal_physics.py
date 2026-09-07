#!/usr/bin/env python3
"""Benchmark season-to-date temperature physics for lake ice-out prediction.

Question: ~30 days before a lake's prior historical median ice-out date, do winter
freezing-degree and spring-thaw anomalies improve prediction of that year's ice-out?

Data discipline:
- ice-out observations: NSIDC G01377
- meteorology: NASA POWER daily T2M (native ~0.5 x 0.625 degree meteorology)
- every test case's lake median and climate anomalies use ONLY years before test year
- model evaluation uses grouped cross-validation by lakecode, so no target lake appears
  in both train and test folds
"""
import csv, datetime as dt, io, json, math, statistics, time, urllib.parse, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from sklearn.compose import TransformedTargetRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT=Path('north-america/data/seasonal-physics')
ROOT.mkdir(parents=True,exist_ok=True)
HIST=Path('north-america/data/ice-history/nsidc-calibration.json')
OUT=ROOT/'benchmark.json'
FEATURES=ROOT/'features.json'
NSIDC='https://noaadata.apps.nsidc.org/NOAA/G01377/liag_freeze_thaw_table.csv'
POWER='https://power.larc.nasa.gov/api/temporal/daily/point'
START_YEAR=1982
END_YEAR=2025
MAX_LAKES=140
MIN_PRIOR_ICE=10
MIN_PRIOR_CLIMATE=8
FORECAST_LEAD_DAYS=30


def pct(xs,p):
    s=sorted(xs)
    if not s:return None
    return s[min(len(s)-1,round((len(s)-1)*p))]
def metrics(errs):
    ae=[abs(float(x)) for x in errs]
    return {'n':len(ae),'mae':round(statistics.mean(ae),3),'median_abs_error':round(statistics.median(ae),3),'p80_abs_error':round(pct(ae,.8),3),'p90_abs_error':round(pct(ae,.9),3),'bias_days':round(statistics.mean(float(x) for x in errs),3)} if ae else {'n':0}
def fetch_json(url,tries=4):
    last=None
    for i in range(tries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'chrisizworski-ice-out/1.0'})
            with urllib.request.urlopen(req,timeout=90) as r:return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            last=e;time.sleep(1.5*(i+1))
    raise last

def load_ice_events():
    raw=urllib.request.urlopen(NSIDC,timeout=90).read().decode('utf-8-sig')
    rows=csv.DictReader(io.StringIO(raw)); by=defaultdict(lambda:defaultdict(list))
    allowed={'CANADA','UNITED STATES','USA','UNITED STATES OF AMERICA'}
    for r in rows:
        if r.get('lakeorriver','').strip().upper()!='L' or r.get('country','').strip().upper() not in allowed:continue
        try:
            y=int(r['iceoff_year']);m=int(r['iceoff_month']);d=int(r['iceoff_day']);date=dt.date(y,m,d)
        except:continue
        if y<1900:continue
        by[r['lakecode'].strip()][y].append(date.timetuple().tm_yday)
    return {k:{y:statistics.median(ds) for y,ds in years.items()} for k,years in by.items()}

def select_lakes(summary,events):
    cand=[]
    for h in summary['lakes']:
        code=h['lakecode'];ev=events.get(code,{})
        recent=sum(1 for y in ev if START_YEAR<=y<=END_YEAR)
        if h.get('records',0)>=20 and recent>=10 and 41<=float(h['lat'])<=72:
            cand.append((recent,h))
    cand.sort(key=lambda x:(-x[0],-x[1].get('records',0)))
    # Geographic diversity: first pass one lake per coarse 2-degree cell, then fill by record count.
    out=[];seen=set()
    for _,h in cand:
        cell=(math.floor(float(h['lat'])/2),math.floor(float(h['lon'])/2))
        if cell in seen:continue
        seen.add(cell);out.append(h)
        if len(out)>=MAX_LAKES:break
    if len(out)<MAX_LAKES:
        have={h['lakecode'] for h in out}
        for _,h in cand:
            if h['lakecode'] not in have:out.append(h);have.add(h['lakecode'])
            if len(out)>=MAX_LAKES:break
    return out

def power_url(h):
    q={'parameters':'T2M','community':'AG','longitude':str(h['lon']),'latitude':str(h['lat']),'start':'19810101','end':f'{END_YEAR}1231','format':'JSON','user':'chrisizworski-ice-out'}
    return POWER+'?'+urllib.parse.urlencode(q)
def fetch_power(h):
    j=fetch_json(power_url(h));par=j.get('properties',{}).get('parameter',{}).get('T2M',{})
    out={}
    for k,v in par.items():
        try:
            d=dt.datetime.strptime(k,'%Y%m%d').date();v=float(v)
            if v>-900:out[d]=v
        except:pass
    if len(out)<1000:raise RuntimeError(f"Too little POWER data for {h['lakecode']}: {len(out)}")
    return h['lakecode'],out

def period_feature(weather,year,cutoff_doy):
    cutoff=dt.date(year,1,1)+dt.timedelta(days=int(round(cutoff_doy))-1)
    start=dt.date(year-1,11,1)
    if cutoff<=start:return None
    dates=[];d=start
    while d<=cutoff:
        if d in weather:dates.append((d,weather[d]))
        d+=dt.timedelta(days=1)
    expected=(cutoff-start).days+1
    if len(dates)<expected*.90:return None
    fdd=sum(max(0,-t) for _,t in dates)
    jan1=dt.date(year,1,1)
    tdd=sum(max(0,t) for d,t in dates if d>=jan1)
    last=[t for d,t in dates if d>cutoff-dt.timedelta(days=14)]
    last14=statistics.mean(last) if len(last)>=10 else None
    warm14=sum(max(0,t) for d,t in dates if d>cutoff-dt.timedelta(days=14))
    return {'fdd':fdd,'tdd':tdd,'last14':last14,'warm14':warm14,'cutoff_doy':cutoff.timetuple().tm_yday}

def build_cases(lakes,events,weather_by):
    cases=[]
    for h in lakes:
        code=h['lakecode'];ev=events[code];weather=weather_by.get(code)
        if not weather:continue
        years=sorted(y for y in ev if START_YEAR<=y<=END_YEAR)
        for y in years:
            prior_ice=[ev[py] for py in ev if py<y]
            if len(prior_ice)<MIN_PRIOR_ICE:continue
            prior_median=statistics.median(prior_ice)
            cutoff_doy=prior_median-FORECAST_LEAD_DAYS
            cur=period_feature(weather,y,cutoff_doy)
            if not cur:continue
            prior_feats=[]
            for py in range(max(1982,y-20),y):
                pf=period_feature(weather,py,cutoff_doy)
                if pf:prior_feats.append(pf)
            if len(prior_feats)<MIN_PRIOR_CLIMATE:continue
            med={k:statistics.median([p[k] for p in prior_feats if p[k] is not None]) for k in ['fdd','tdd','last14','warm14']}
            x=[(cur['fdd']-med['fdd'])/100.0,(cur['tdd']-med['tdd'])/50.0,(cur['last14']-med['last14']),(cur['warm14']-med['warm14'])/50.0]
            obs=float(ev[y]);resid=obs-float(prior_median)
            cases.append({'lakecode':code,'lake':h['name'],'year':y,'lat':h['lat'],'lon':h['lon'],'prior_median':round(prior_median,2),'observed':obs,'residual':round(resid,3),'x':[round(v,5) for v in x],'raw':{k:round(cur[k],3) for k in ['fdd','tdd','last14','warm14']}})
    return cases

def grouped_cv(cases):
    X=np.array([c['x'] for c in cases],dtype=float);y=np.array([c['residual'] for c in cases],dtype=float);groups=np.array([c['lakecode'] for c in cases])
    unique=len(set(groups));folds=min(8,unique)
    gkf=GroupKFold(n_splits=folds);pred=np.zeros(len(cases));fold_meta=[]
    for n,(tr,te) in enumerate(gkf.split(X,y,groups),1):
        model=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=12.0))])
        model.fit(X[tr],y[tr]);pred[te]=model.predict(X[te]);fold_meta.append({'fold':n,'train_n':len(tr),'test_n':len(te),'test_lakes':len(set(groups[te]))})
    base_err=-y # prior median - observed
    physics_err=pred-y # (prior median + predicted residual) - observed
    full=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=12.0))]);full.fit(X,y)
    scaler=full.named_steps['scale'];ridge=full.named_steps['ridge']
    return base_err,physics_err,pred,fold_meta,{'feature_order':['fdd_anom_per_100Cday','tdd_anom_per_50Cday','last14_temp_anom_C','warm14_anom_per_50Cday'],'mean':[round(float(v),6) for v in scaler.mean_],'scale':[round(float(v),6) for v in scaler.scale_],'coef_scaled':[round(float(v),6) for v in ridge.coef_],'intercept':round(float(ridge.intercept_),6),'alpha':12.0}

summary=json.loads(HIST.read_text())
events=load_ice_events();lakes=select_lakes(summary,events)
print(f'Selected {len(lakes)} NSIDC lakes for POWER sampling')
weather_by={};failures=[]
with ThreadPoolExecutor(max_workers=4) as ex:
    fut={ex.submit(fetch_power,h):h for h in lakes}
    for f in as_completed(fut):
        h=fut[f]
        try:
            code,w=f.result();weather_by[code]=w;print('POWER',code,len(w))
        except Exception as e:
            failures.append({'lakecode':h['lakecode'],'lake':h['name'],'error':str(e)});print('FAIL',h['lakecode'],e)

cases=build_cases(lakes,events,weather_by)
if len(cases)<300 or len({c['lakecode'] for c in cases})<30:raise RuntimeError(f'Insufficient benchmark sample: {len(cases)} cases / {len(set(c["lakecode"] for c in cases))} lakes')
base_err,phys_err,pred,folds,model=grouped_cv(cases)
base=metrics(base_err);physics=metrics(phys_err)
improved=sum(abs(phys_err[i])<abs(base_err[i]) for i in range(len(cases)))/len(cases)
relative=(base['mae']-physics['mae'])/base['mae'] if base['mae'] else 0
worst=sorted([{'lake':c['lake'],'year':c['year'],'observed':c['observed'],'prior_median':c['prior_median'],'physics_pred':round(c['prior_median']+float(pred[i]),2),'base_error':round(float(base_err[i]),2),'physics_error':round(float(phys_err[i]),2)} for i,c in enumerate(cases)],key=lambda r:abs(r['physics_error']),reverse=True)[:25]
out={'version':1,'question':f'Do season-to-date temperature anomalies improve ice-out prediction {FORECAST_LEAD_DAYS} days before prior median?','ice_source':'NSIDC G01377','weather_source':'NASA POWER daily T2M','data_discipline':'Each case uses only earlier years for its lake prior/climate anomaly; grouped CV holds out entire lakes from regression training.','selected_lakes':len(lakes),'weather_lakes_succeeded':len(weather_by),'weather_failures':failures,'cases':len(cases),'case_lakes':len(set(c['lakecode'] for c in cases)),'baseline_prior_median':base,'seasonal_physics_grouped_cv':physics,'improved_fraction':round(improved,4),'relative_mae_improvement':round(relative,4),'release_gate':{'minimum_relative_mae_improvement':0.08,'maximum_physics_mae_days':7.5,'passes':bool(relative>=0.08 and physics['mae']<=7.5)},'model':model,'folds':folds,'worst_errors':worst,'notes':['NASA POWER meteorology is coarse-scale; anomalies are used to reduce terrain/elevation bias.','This test does not yet include snowpack, satellite state, wind or radiation.','A passing result qualifies temperature physics as an additional model layer; it does not by itself validate final probabilities.']}
OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
FEATURES.write_text(json.dumps({'version':1,'cases':cases},separators=(',',':')),encoding='utf-8')
print(json.dumps(out,indent=2))
