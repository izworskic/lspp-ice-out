#!/usr/bin/env python3
"""Test whether observed snow depth improves temperature-only ice-out forecasts.

Validation discipline:
- Ice-out truth: NSIDC G01377.
- Temperature: NASA POWER daily T2M.
- Snow depth: NOAA/NCEI GHCN-Daily SNWD from nearby stations.
- Every lake-year feature anomaly uses only prior years.
- GroupKFold holds out whole lakes when comparing temperature-only vs temperature+snow.
- The snow model is accepted only if it improves held-out MAE on the same snow-observed cases.
"""
from __future__ import annotations

import csv, datetime as dt, io, json, math, statistics, time, urllib.error, urllib.parse, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

HIST=Path('north-america/data/ice-history/nsidc-calibration.json')
OUT=Path('north-america/data/seasonal-physics/snowpack-increment.json')
NSIDC='https://noaadata.apps.nsidc.org/NOAA/G01377/liag_freeze_thaw_table.csv'
POWER='https://power.larc.nasa.gov/api/temporal/daily/point'
GHCN='https://www.ncei.noaa.gov/pub/data/ghcn/daily/'
START_YEAR=1982
END_YEAR=2025
MAX_LAKES=100
LEADS=[45,30,21,14,7]
MAX_STATION_KM=100


def pct(xs,p):
    s=sorted(xs)
    if not s:return None
    pos=(len(s)-1)*p;lo=math.floor(pos);hi=math.ceil(pos)
    return s[lo] if lo==hi else s[lo]*(hi-pos)+s[hi]*(pos-lo)

def metrics(err):
    ae=[abs(float(x)) for x in err]
    return {'n':len(ae),'mae':round(statistics.mean(ae),3),'median_abs_error':round(statistics.median(ae),3),'p80_abs_error':round(pct(ae,.8),3),'p90_abs_error':round(pct(ae,.9),3),'bias_days':round(statistics.mean(float(x) for x in err),3)}

def fetch_bytes(url,tries=4):
    last=None
    for i in range(tries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'chrisizworski-ice-out/1.0'})
            with urllib.request.urlopen(req,timeout=120) as r:return r.read()
        except urllib.error.HTTPError as e:
            try:detail=e.read().decode('utf-8','replace')[:400]
            except Exception:detail=''
            last=RuntimeError(f'HTTP {e.code}: {detail}')
            if e.code in (404,422):break
        except Exception as e:last=e
        time.sleep(1.5*(i+1))
    raise last

def fetch_json(url):return json.loads(fetch_bytes(url).decode('utf-8'))

def hav(lat1,lon1,lat2,lon2):
    R=6371;p=math.pi/180;dlat=(lat2-lat1)*p;dlon=(lon2-lon1)*p
    a=math.sin(dlat/2)**2+math.cos(lat1*p)*math.cos(lat2*p)*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(a))

def ice_events():
    text=fetch_bytes(NSIDC).decode('utf-8-sig');by=defaultdict(lambda:defaultdict(list));allowed={'CANADA','UNITED STATES','USA','UNITED STATES OF AMERICA'}
    for r in csv.DictReader(io.StringIO(text)):
        if r.get('lakeorriver','').strip().upper()!='L' or r.get('country','').strip().upper() not in allowed:continue
        try:y=int(r['iceoff_year']);d=dt.date(y,int(r['iceoff_month']),int(r['iceoff_day'])).timetuple().tm_yday
        except Exception:continue
        if y>=1900:by[r['lakecode'].strip()][y].append(d)
    return {k:{y:statistics.median(ds) for y,ds in yrs.items()} for k,yrs in by.items()}

def select_lakes(summary,ev):
    cand=[]
    for h in summary['lakes']:
        recent=sum(1 for y in ev.get(h['lakecode'],{}) if START_YEAR<=y<=END_YEAR)
        if h.get('records',0)>=20 and recent>=10 and 41<=float(h['lat'])<=72:cand.append((recent,h))
    cand.sort(key=lambda z:(-z[0],-z[1].get('records',0)));out=[];seen=set()
    for _,h in cand:
        cell=(math.floor(float(h['lat'])/2),math.floor(float(h['lon'])/2))
        if cell in seen:continue
        seen.add(cell);out.append(h)
        if len(out)>=MAX_LAKES:break
    have={h['lakecode'] for h in out}
    for _,h in cand:
        if len(out)>=MAX_LAKES:break
        if h['lakecode'] not in have:out.append(h);have.add(h['lakecode'])
    return out

def power_url(h):
    q={'parameters':'T2M','community':'AG','longitude':h['lon'],'latitude':h['lat'],'start':'19810101','end':f'{END_YEAR}1231','format':'JSON','time-standard':'UTC'}
    return POWER+'?'+urllib.parse.urlencode(q)

def power_weather(h):
    j=fetch_json(power_url(h));p=j.get('properties',{}).get('parameter',{}).get('T2M',{});o={}
    for k,v in p.items():
        try:d=dt.datetime.strptime(k,'%Y%m%d').date();v=float(v)
        except Exception:continue
        if v>-900:o[d]=v
    if len(o)<1000:raise RuntimeError(f'too little POWER data: {len(o)}')
    return h['lakecode'],o

def temp_feature(w,year,cutoff_doy):
    end=dt.date(year,1,1)+dt.timedelta(days=int(round(cutoff_doy))-1);start=dt.date(year-1,11,1);vals=[];d=start
    while d<=end:
        if d in w:vals.append((d,w[d]))
        d+=dt.timedelta(days=1)
    expected=(end-start).days+1
    if expected<=0 or len(vals)<expected*.9:return None
    fdd=sum(max(0,-t) for _,t in vals);jan=dt.date(year,1,1);tdd=sum(max(0,t) for d,t in vals if d>=jan)
    last=[t for d,t in vals if d>end-dt.timedelta(days=14)]
    if len(last)<10:return None
    return {'fdd':fdd,'tdd':tdd,'last14':statistics.mean(last),'warm14':sum(max(0,t) for d,t in vals if d>end-dt.timedelta(days=14))}

def load_snwd_inventory():
    text=fetch_bytes(GHCN+'ghcnd-inventory.txt').decode('utf-8','replace');rows=[]
    for line in text.splitlines():
        # ID(11) LAT(9) LON(10) ELEMENT(5) FIRST(5) LAST(5)
        try:
            sid=line[0:11].strip();lat=float(line[12:20]);lon=float(line[21:30]);element=line[31:35].strip();first=int(line[36:40]);last=int(line[41:45])
        except Exception:continue
        if element=='SNWD' and last>=START_YEAR and first<=END_YEAR:rows.append((sid,lat,lon,first,last))
    return rows

def parse_dly_snwd(raw):
    out={}
    for line in raw.decode('ascii','replace').splitlines():
        if len(line)<21 or line[17:21]!='SNWD':continue
        try:y=int(line[11:15]);m=int(line[15:17])
        except Exception:continue
        if y<1981 or y>END_YEAR:continue
        for day in range(1,32):
            off=21+(day-1)*8
            try:v=int(line[off:off+5]);q=line[off+6:off+7]
            except Exception:continue
            if v==-9999 or q.strip():continue
            try:d=dt.date(y,m,day)
            except Exception:continue
            out[d]=float(v) # mm
    return out

def choose_snow_station(h,inventory,cache):
    ranked=sorted(((hav(float(h['lat']),float(h['lon']),s[1],s[2]),s) for s in inventory),key=lambda z:z[0])
    for dist,s in ranked[:12]:
        if dist>MAX_STATION_KM:break
        sid=s[0]
        if sid not in cache:
            try:cache[sid]=parse_dly_snwd(fetch_bytes(GHCN+f'all/{sid}.dly'))
            except Exception:cache[sid]={}
        data=cache[sid]
        # Require meaningful multi-decade coverage; exact per-year coverage is checked later.
        if len(data)>=1000:return {'id':sid,'distance_km':dist,'lat':s[1],'lon':s[2],'first':s[3],'last':s[4],'data':data}
    return None

def snow_feature(sn,year,cutoff_doy):
    end=dt.date(year,1,1)+dt.timedelta(days=int(round(cutoff_doy))-1);start=dt.date(year-1,11,1)
    vals=[];d=start
    while d<=end:
        if d in sn:vals.append((d,sn[d]))
        d+=dt.timedelta(days=1)
    expected=(end-start).days+1
    if expected<=0 or len(vals)<expected*.65:return None
    recent=[(d,v) for d,v in vals if d>end-dt.timedelta(days=14)]
    if len(recent)<8:return None
    near=[v for d,v in vals if d>end-dt.timedelta(days=3)]
    if not near:return None
    return {'cutoff':statistics.median(near),'mean14':statistics.mean(v for _,v in recent),'snowdays':sum(v>0 for _,v in vals),'max':max(v for _,v in vals),'coverage':len(vals)/expected}

def build_cases(lead,lakes,ev,temp_by,snow_by):
    out=[]
    for h in lakes:
        code=h['lakecode'];tw=temp_by.get(code);sw=snow_by.get(code)
        if not tw or not sw:continue
        for y in sorted(y for y in ev[code] if START_YEAR<=y<=END_YEAR):
            prior=[ev[code][py] for py in ev[code] if py<y]
            if len(prior)<10:continue
            med=statistics.median(prior);cut=med-lead;curt=temp_feature(tw,y,cut);curs=snow_feature(sw['data'],y,cut)
            if not curt or not curs:continue
            ht=[];hs=[]
            for py in range(max(1982,y-20),y):
                tf=temp_feature(tw,py,cut);sf=snow_feature(sw['data'],py,cut)
                if tf and sf:ht.append(tf);hs.append(sf)
            if len(ht)<8:continue
            tm={k:statistics.median([x[k] for x in ht]) for k in ['fdd','tdd','last14','warm14']}
            sm={k:statistics.median([x[k] for x in hs]) for k in ['cutoff','mean14','snowdays','max']}
            xt=[(curt['fdd']-tm['fdd'])/100,(curt['tdd']-tm['tdd'])/50,curt['last14']-tm['last14'],(curt['warm14']-tm['warm14'])/50]
            xs=[(curs['cutoff']-sm['cutoff'])/100,(curs['mean14']-sm['mean14'])/100,(curs['snowdays']-sm['snowdays'])/10,(curs['max']-sm['max'])/100]
            out.append({'lakecode':code,'year':y,'resid':float(ev[code][y]-med),'temp':xt,'snow':xs,'station_km':sw['distance_km']})
    return out

def grouped_compare(cases):
    yt=np.array([c['resid'] for c in cases],float);Xt=np.array([c['temp'] for c in cases],float);Xts=np.array([c['temp']+c['snow'] for c in cases],float);g=np.array([c['lakecode'] for c in cases])
    folds=min(8,len(set(g)));pt=np.zeros(len(yt));pts=np.zeros(len(yt))
    for tr,te in GroupKFold(folds).split(Xt,yt,g):
        mt=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=12.0))]);ms=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=12.0))])
        mt.fit(Xt[tr],yt[tr]);ms.fit(Xts[tr],yt[tr]);pt[te]=mt.predict(Xt[te]);pts[te]=ms.predict(Xts[te])
    et=pt-yt;ets=pts-yt;mt=metrics(et);mts=metrics(ets);rel=(mt['mae']-mts['mae'])/mt['mae'] if mt['mae'] else 0
    full=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=12.0))]);full.fit(Xts,yt);sc=full.named_steps['scale'];rg=full.named_steps['ridge']
    return {'cases':len(cases),'lakes':len(set(g)),'median_station_km':round(statistics.median(c['station_km'] for c in cases),1),'temperature_only':mt,'temperature_plus_snow':mts,'relative_mae_improvement_vs_temperature':round(rel,4),'improved_fraction_vs_temperature':round(sum(abs(ets[i])<abs(et[i]) for i in range(len(yt)))/len(yt),4),'passes':bool(rel>=.03 and mts['mae']<mt['mae'] and len(set(g))>=25),'release_gate':{'minimum_relative_mae_improvement_vs_temperature':0.03,'minimum_lakes':25},'model_temp_plus_snow':{'feature_order':['fdd_anom_per_100Cday','tdd_anom_per_50Cday','last14_temp_anom_C','warm14_anom_per_50Cday','snowdepth_cutoff_anom_per_100mm','snowdepth_mean14_anom_per_100mm','snowcovered_days_anom_per_10d','max_snowdepth_anom_per_100mm'],'mean':[round(float(v),6) for v in sc.mean_],'scale':[round(float(v),6) for v in sc.scale_],'coef_scaled':[round(float(v),6) for v in rg.coef_],'intercept':round(float(rg.intercept_),6),'alpha':12.0}}

summary=json.loads(HIST.read_text());ev=ice_events();lakes=select_lakes(summary,ev)
print(f'Selected {len(lakes)} lakes')
# NASA POWER temperatures.
temp_by={};temp_fail=[]
with ThreadPoolExecutor(max_workers=3) as ex:
    fs={ex.submit(power_weather,h):h for h in lakes}
    for f in as_completed(fs):
        h=fs[f]
        try:k,w=f.result();temp_by[k]=w
        except Exception as e:temp_fail.append({'lakecode':h['lakecode'],'error':str(e)})
if len(temp_by)<80:raise RuntimeError(f'Insufficient POWER coverage {len(temp_by)}/{len(lakes)}')
# GHCN observed snow depth.
inv=load_snwd_inventory();cache={};snow_by={};snow_fail=[]
for i,h in enumerate(lakes,1):
    st=choose_snow_station(h,inv,cache)
    if st:snow_by[h['lakecode']]=st
    else:snow_fail.append({'lakecode':h['lakecode'],'lake':h['name']})
    if i%10==0:print(f'Snow station matching {i}/{len(lakes)}; matched {len(snow_by)}')
results={}
for lead in LEADS:
    cases=build_cases(lead,lakes,ev,temp_by,snow_by)
    if len(cases)<250 or len(set(c['lakecode'] for c in cases))<25:
        results[str(lead)]={'cases':len(cases),'lakes':len(set(c['lakecode'] for c in cases)),'passes':False,'reason':'insufficient snow-observed sample'}
    else:results[str(lead)]=grouped_compare(cases)
out={'version':1,'question':'Does observed snow depth add held-out predictive skill beyond the validated temperature-physics model?','ice_source':'NSIDC G01377','temperature_source':'NASA POWER daily T2M UTC','snow_source':'NOAA/NCEI GHCN-Daily SNWD','snow_station_rule':f'nearest usable SNWD station within {MAX_STATION_KM} km; per-case winter coverage >=65% and recent-14-day coverage >=8 observations','validation':'rolling-origin feature anomalies; GroupKFold holds out whole lakes; temperature-only and temperature+snow are compared on identical snow-observed cases','selected_lakes':len(lakes),'temperature_lakes':len(temp_by),'snow_station_lakes':len(snow_by),'temperature_failures':temp_fail,'snow_station_failures':snow_fail,'lead_days':LEADS,'results':results,'deployment_rule':'Only add snow features at lead times with passes=true; otherwise retain temperature-only physics. GHCN point snow depth is a benchmark signal, not assumed lake-surface snow depth.'}
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out,indent=2))
