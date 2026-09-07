#!/usr/bin/env python3
import json, math, statistics
from pathlib import Path

SRC=Path('north-america/data/ice-history/nsidc-calibration.json')
OUT=Path('north-america/data/ice-history/validation.json')

def clamp(v,a,b):return max(a,min(b,v))
def hav(a,b):
    R=6371;p=math.pi/180
    dlat=(b['lat']-a['lat'])*p;dlon=(b['lon']-a['lon'])*p
    s=math.sin(dlat/2)**2+math.cos(a['lat']*p)*math.cos(b['lat']*p)*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(s))
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
D={'shallow':-4,'medium':0,'deep':4,'verydeep':8};A={'small':-2,'medium':0,'large':2,'huge':5}
def baseline(h):
    lat=85+(h['lat']-40)*4.2
    elev=(h.get('elevation_m') or 0)/100*.8
    return clamp(round(lat+elev+D[depth_class(h.get('mean_depth_m'))]+A[area_class(h.get('surface_area_km2'))]),92,220)
def regional(target,rows):
    nearby=[]
    for h in rows:
        if h['lakecode']==target['lakecode'] or h['country']!=target['country'] or h['records']<15:continue
        d=hav(target,h)
        if d<=500:nearby.append((d,h))
    nearby.sort(key=lambda x:x[0]);nearby=nearby[:16]
    if len(nearby)<3:return None,0
    num=den=0
    for d,h in nearby:
        residual=h['median_doy']-baseline(h)
        w=math.sqrt(h['records'])*math.exp(-d/220)
        num+=residual*w;den+=w
    return clamp(num/den,-15,15),len(nearby)
def metrics(errs):
    ae=sorted(abs(x) for x in errs)
    def pct(p):
        if not ae:return None
        return ae[min(len(ae)-1,round((len(ae)-1)*p))]
    return {'n':len(errs),'mae':round(statistics.mean(ae),2),'median_abs_error':round(statistics.median(ae),2),'p80_abs_error':round(pct(.8),2),'p90_abs_error':round(pct(.9),2),'bias_days':round(statistics.mean(errs),2)}

data=json.loads(SRC.read_text())['lakes']
rows=[h for h in data if h['records']>=15]
base_err=[];reg_err=[];improved=0;reg_n=0;examples=[]
for h in rows:
    obs=h['median_doy'];b=baseline(h);base_err.append(b-obs)
    corr,n=regional(h,rows)
    if corr is None:continue
    pred=round(b+corr);e=pred-obs;reg_err.append(e);reg_n+=1
    if abs(e)<abs(b-obs):improved+=1
    examples.append({'lake':h['name'],'country':h['country'],'observed':obs,'baseline':b,'regional':pred,'base_error':round(b-obs,1),'regional_error':round(e,1),'neighbors':n})
examples.sort(key=lambda x:abs(x['regional_error']),reverse=True)
out={'method':'leave-one-lake-out; target lake never contributes to its regional correction','eligibility':'NSIDC lakes with >=15 usable ice-out records','baseline':metrics(base_err),'regional_residual':metrics(reg_err),'regional_improved_fraction':round(improved/reg_n,3) if reg_n else None,'worst_regional_errors':examples[:20]}
OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
print(json.dumps(out,indent=2))
