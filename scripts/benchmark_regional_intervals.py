#!/usr/bin/env python3
import csv, datetime as dt, hashlib, io, json, math, statistics, urllib.request
from collections import defaultdict
from pathlib import Path

CAL=Path('north-america/data/ice-history/nsidc-calibration.json')
OUT=Path('north-america/data/ice-history/regional-interval-validation.json')
RAW='https://noaadata.apps.nsidc.org/NOAA/G01377/liag_freeze_thaw_table.csv'
D={'shallow':-4,'medium':0,'deep':4,'verydeep':8};A={'small':-2,'medium':0,'large':2,'huge':5}

def clamp(v,a,b):return max(a,min(b,v))
def area_class(a):
    if not a or a<=0:return 'medium'
    if a<2:return 'small'
    if a<50:return 'medium'
    if a<500:return 'large'
    return 'huge'
def depth_class(d):
    if not d or d<=0:return 'medium'
    if d<3:return 'shallow'
    if d<12:return 'medium'
    if d<35:return 'deep'
    return 'verydeep'
def baseline(h):
    return clamp(round(85+(h['lat']-40)*4.2+(h.get('elevation_m') or 0)/100*.8+D[depth_class(h.get('mean_depth_m'))]+A[area_class(h.get('surface_area_km2'))]),92,220)
def hav(a,b):
    R=6371;p=math.pi/180;dlat=(b['lat']-a['lat'])*p;dlon=(b['lon']-a['lon'])*p
    q=math.sin(dlat/2)**2+math.cos(a['lat']*p)*math.cos(b['lat']*p)*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(q))
def predict(t,rows):
    near=[]
    for h in rows:
        if h['lakecode']==t['lakecode'] or h['country']!=t['country'] or h['records']<15:continue
        d=hav(t,h)
        if d<=500:near.append((d,h))
    near.sort(key=lambda z:z[0]);near=near[:8]
    if len(near)<3:return None
    num=den=0
    for d,h in near:
        elev=1
        if t.get('elevation_m') is not None and h.get('elevation_m') is not None:elev=math.exp(-abs(t['elevation_m']-h['elevation_m'])/250)
        depth=1
        if t.get('mean_depth_m') and h.get('mean_depth_m') and t['mean_depth_m']>0 and h['mean_depth_m']>0:depth=math.exp(-abs(math.log(t['mean_depth_m']/h['mean_depth_m']))/2)
        w=math.sqrt(h['records'])*math.exp(-d/140)*elev*depth
        num+=(h['median_doy']-baseline(h))*w;den+=w
    return round(baseline(t)+clamp(num/den,-15,15)) if den else None
def percentile(xs,p):
    s=sorted(xs);pos=(len(s)-1)*p;lo=math.floor(pos);hi=math.ceil(pos)
    return s[lo] if lo==hi else s[lo]*(hi-pos)+s[hi]*(pos-lo)
def events():
    text=urllib.request.urlopen(RAW,timeout=90).read().decode('utf-8-sig');by=defaultdict(lambda:defaultdict(list));allowed={'CANADA','UNITED STATES','USA','UNITED STATES OF AMERICA'}
    for r in csv.DictReader(io.StringIO(text)):
        if r.get('lakeorriver','').strip().upper()!='L' or r.get('country','').strip().upper() not in allowed:continue
        try:y=int(r['iceoff_year']);d=dt.date(y,int(r['iceoff_month']),int(r['iceoff_day'])).timetuple().tm_yday
        except:continue
        if y>=1950:by[r['lakecode'].strip()][y].append(d)
    return {k:[statistics.median(ds) for _,ds in sorted(v.items())] for k,v in by.items()}
def score(resid,lo,hi):
    if not resid:return {'n':0}
    inside=sum(lo<=r<=hi for r in resid)/len(resid)
    return {'n':len(resid),'coverage':round(inside,4),'mean_width_days':round(hi-lo,2),'mean_residual':round(statistics.mean(resid),3),'median_abs_residual':round(statistics.median(abs(r) for r in resid),3)}

rows=[h for h in json.loads(CAL.read_text())['lakes'] if h['records']>=15];ev=events();train=[];test=[]
for h in rows:
    pred=predict(h,rows);obs=ev.get(h['lakecode'],[])
    if pred is None or len(obs)<10:continue
    residuals=[o-pred for o in obs]
    (test if int(hashlib.sha1(h['lakecode'].encode()).hexdigest()[:8],16)%5==0 else train).extend(residuals)
lo10=percentile(train,.10);hi90=percentile(train,.90)
lo25=percentile(train,.25);hi75=percentile(train,.75)
half80=percentile([abs(x) for x in train],.80)
half50=percentile([abs(x) for x in train],.50)
out={
 'method':'regional median residual intervals selected on deterministic 80% lake training split and tested on held-out 20% lakes',
 'train_cases':len(train),'test_cases':len(test),
 'interval80':{
   'asymmetric_offsets_days':{'p10':round(lo10,2),'p90':round(hi90,2)},
   'symmetric_halfwidth_days':round(half80,2),
   'train_asymmetric':score(train,lo10,hi90),'test_asymmetric':score(test,lo10,hi90),
   'train_symmetric':score(train,-half80,half80),'test_symmetric':score(test,-half80,half80)
 },
 'interval50':{
   'asymmetric_offsets_days':{'p25':round(lo25,2),'p75':round(hi75,2)},
   'symmetric_halfwidth_days':round(half50,2),
   'train_asymmetric':score(train,lo25,hi75),'test_asymmetric':score(test,lo25,hi75),
   'train_symmetric':score(train,-half50,half50),'test_symmetric':score(test,-half50,half50)
 }
}
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out,indent=2))
