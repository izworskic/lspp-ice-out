#!/usr/bin/env python3
"""Validate the actual regional-history + seasonal-temperature production stack.

For every historical target lake-year:
1. Build the regional baseline from OTHER lakes only, using only neighbor ice-out
   observations from years before the target year.
2. Build target-lake temperature anomalies using only prior climate years.
3. GroupKFold holds out whole target lakes while fitting the weather residual model.

This answers whether seasonal physics may safely modify regional-history lakes.
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
OUT=Path('north-america/data/seasonal-physics/regional-plus-physics.json')
NSIDC='https://noaadata.apps.nsidc.org/NOAA/G01377/liag_freeze_thaw_table.csv'
POWER='https://power.larc.nasa.gov/api/temporal/daily/point'
START_YEAR=1982;END_YEAR=2025;MAX_LAKES=100;LEADS=[45,30,21,14,7]
D={'shallow':-4,'medium':0,'deep':4,'verydeep':8};A={'small':-2,'medium':0,'large':2,'huge':5}

def clamp(v,a,b):return max(a,min(b,v))
def pct(xs,p):
 s=sorted(xs);pos=(len(s)-1)*p;lo=math.floor(pos);hi=math.ceil(pos);return s[lo] if lo==hi else s[lo]*(hi-pos)+s[hi]*(pos-lo)
def metrics(err):
 ae=[abs(float(x)) for x in err];return {'n':len(ae),'mae':round(statistics.mean(ae),3),'median_abs_error':round(statistics.median(ae),3),'p80_abs_error':round(pct(ae,.8),3),'p90_abs_error':round(pct(ae,.9),3),'bias_days':round(statistics.mean(float(x) for x in err),3)}
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
def morph(h):return clamp(round(85+(float(h['lat'])-40)*4.2+(h.get('elevation_m') or 0)/100*.8+D[depth_class(h.get('mean_depth_m'))]+A[area_class(h.get('surface_area_km2'))]),92,220)
def hav(a,b):
 R=6371;p=math.pi/180;dlat=(float(b['lat'])-float(a['lat']))*p;dlon=(float(b['lon'])-float(a['lon']))*p
 q=math.sin(dlat/2)**2+math.cos(float(a['lat'])*p)*math.cos(float(b['lat'])*p)*math.sin(dlon/2)**2
 return 2*R*math.asin(math.sqrt(q))
def fetch_json(url,tries=4):
 last=None
 for i in range(tries):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'chrisizworski-ice-out/1.0'})
   with urllib.request.urlopen(req,timeout=120) as r:return json.loads(r.read().decode())
  except urllib.error.HTTPError as e:
   try:detail=e.read().decode('utf-8','replace')[:400]
   except:detail=''
   last=RuntimeError(f'HTTP {e.code}: {detail}')
   if e.code==422:break
  except Exception as e:last=e
  time.sleep(2*(i+1))
 raise last
def events():
 raw=urllib.request.urlopen(NSIDC,timeout=90).read().decode('utf-8-sig');by=defaultdict(lambda:defaultdict(list));allowed={'CANADA','UNITED STATES','USA','UNITED STATES OF AMERICA'}
 for r in csv.DictReader(io.StringIO(raw)):
  if r.get('lakeorriver','').strip().upper()!='L' or r.get('country','').strip().upper() not in allowed:continue
  try:y=int(r['iceoff_year']);d=dt.date(y,int(r['iceoff_month']),int(r['iceoff_day'])).timetuple().tm_yday
  except:continue
  if y>=1900:by[r['lakecode'].strip()][y].append(d)
 return {k:{y:statistics.median(ds) for y,ds in yrs.items()} for k,yrs in by.items()}
def select(summary,ev):
 c=[]
 for h in summary['lakes']:
  recent=sum(1 for y in ev.get(h['lakecode'],{}) if START_YEAR<=y<=END_YEAR)
  if h.get('records',0)>=20 and recent>=10 and 41<=float(h['lat'])<=72:c.append((recent,h))
 c.sort(key=lambda z:(-z[0],-z[1].get('records',0)));out=[];seen=set()
 for _,h in c:
  cell=(math.floor(float(h['lat'])/2),math.floor(float(h['lon'])/2))
  if cell in seen:continue
  seen.add(cell);out.append(h)
  if len(out)>=MAX_LAKES:break
 have={h['lakecode'] for h in out}
 for _,h in c:
  if len(out)>=MAX_LAKES:break
  if h['lakecode'] not in have:out.append(h);have.add(h['lakecode'])
 return out
def power_url(h):
 q={'parameters':'T2M','community':'AG','longitude':h['lon'],'latitude':h['lat'],'start':'19810101','end':f'{END_YEAR}1231','format':'JSON','time-standard':'UTC'}
 return POWER+'?'+urllib.parse.urlencode(q)
def weather(h):
 j=fetch_json(power_url(h));p=j.get('properties',{}).get('parameter',{}).get('T2M',{});o={}
 for k,v in p.items():
  try:d=dt.datetime.strptime(k,'%Y%m%d').date();v=float(v)
  except:continue
  if v>-900:o[d]=v
 if len(o)<1000:raise RuntimeError(f'too little POWER data {len(o)}')
 return h['lakecode'],o
def feature(w,year,cutoff):
 end=dt.date(year,1,1)+dt.timedelta(days=int(round(cutoff))-1);start=dt.date(year-1,11,1);vals=[];d=start
 while d<=end:
  if d in w:vals.append((d,w[d]))
  d+=dt.timedelta(days=1)
 exp=(end-start).days+1
 if exp<=0 or len(vals)<exp*.9:return None
 fdd=sum(max(0,-t) for _,t in vals);jan=dt.date(year,1,1);tdd=sum(max(0,t) for d,t in vals if d>=jan);last=[t for d,t in vals if d>end-dt.timedelta(days=14)]
 if len(last)<10:return None
 return {'fdd':fdd,'tdd':tdd,'last14':statistics.mean(last),'warm14':sum(max(0,t) for d,t in vals if d>end-dt.timedelta(days=14))}
def regional_baseline(target,year,rows,ev):
 near=[]
 for h in rows:
  if h['lakecode']==target['lakecode'] or h['country']!=target['country']:continue
  prior=[d for y,d in ev.get(h['lakecode'],{}).items() if y<year and y>=1950]
  if len(prior)<10:continue
  dist=hav(target,h)
  if dist<=500:near.append((dist,h,statistics.median(prior),len(prior)))
 near.sort(key=lambda z:z[0]);near=near[:8]
 if len(near)<3:return None
 num=den=0
 for dist,h,med,nrec in near:
  elev=1
  if target.get('elevation_m') is not None and h.get('elevation_m') is not None:elev=math.exp(-abs(float(target['elevation_m'])-float(h['elevation_m']))/250)
  depth=1
  td=target.get('mean_depth_m');hd=h.get('mean_depth_m')
  if td and hd and td>0 and hd>0:depth=math.exp(-abs(math.log(float(td)/float(hd)))/2)
  wt=math.sqrt(nrec)*math.exp(-dist/140)*elev*depth
  num+=(med-morph(h))*wt;den+=wt
 if not den:return None
 return float(clamp(morph(target)+clamp(num/den,-15,15),92,220))
def cases_for(lead,lakes,rows,ev,wb):
 out=[]
 for h in lakes:
  code=h['lakecode'];w=wb.get(code)
  if not w:continue
  for y in sorted(y for y in ev[code] if START_YEAR<=y<=END_YEAR):
   rb=regional_baseline(h,y,rows,ev)
   if rb is None:continue
   # Lead is measured against the regional baseline because that is what production knows.
   cut=rb-lead;cur=feature(w,y,cut)
   if not cur:continue
   hist=[]
   for py in range(max(1982,y-20),y):
    f=feature(w,py,cut)
    if f:hist.append(f)
   if len(hist)<8:continue
   hm={k:statistics.median([x[k] for x in hist]) for k in ['fdd','tdd','last14','warm14']}
   x=[(cur['fdd']-hm['fdd'])/100,(cur['tdd']-hm['tdd'])/50,cur['last14']-hm['last14'],(cur['warm14']-hm['warm14'])/50]
   out.append({'lakecode':code,'year':y,'resid':float(ev[code][y]-rb),'regional':rb,'x':x})
 return out
def fit(cases):
 X=np.array([c['x'] for c in cases],float);y=np.array([c['resid'] for c in cases],float);g=np.array([c['lakecode'] for c in cases]);pred=np.zeros(len(y));folds=min(8,len(set(g)))
 for tr,te in GroupKFold(folds).split(X,y,g):
  m=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=12.0))]);m.fit(X[tr],y[tr]);pred[te]=m.predict(X[te])
 base=-y;err=pred-y;bm=metrics(base);pm=metrics(err);rel=(bm['mae']-pm['mae'])/bm['mae']
 full=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=12.0))]);full.fit(X,y);sc=full.named_steps['scale'];rg=full.named_steps['ridge']
 return {'cases':len(cases),'lakes':len(set(g)),'regional_only':bm,'regional_plus_physics':pm,'relative_mae_improvement':round(rel,4),'improved_fraction':round(sum(abs(err[i])<abs(base[i]) for i in range(len(y)))/len(y),4),'passes':bool(rel>=.08 and pm['mae']<bm['mae']),'model':{'feature_order':['fdd_anom_per_100Cday','tdd_anom_per_50Cday','last14_temp_anom_C','warm14_anom_per_50Cday'],'mean':[round(float(v),6) for v in sc.mean_],'scale':[round(float(v),6) for v in sc.scale_],'coef_scaled':[round(float(v),6) for v in rg.coef_],'intercept':round(float(rg.intercept_),6),'alpha':12.0}}

summary=json.loads(HIST.read_text());rows=[h for h in summary['lakes'] if h.get('records',0)>=10];ev=events();lakes=select(summary,ev);wb={};fails=[]
with ThreadPoolExecutor(max_workers=3) as ex:
 fs={ex.submit(weather,h):h for h in lakes}
 for f in as_completed(fs):
  h=fs[f]
  try:k,w=f.result();wb[k]=w
  except Exception as e:fails.append({'lakecode':h['lakecode'],'error':str(e)})
if len(wb)<80:raise RuntimeError(f'Insufficient POWER coverage {len(wb)}/{len(lakes)}')
results={}
for lead in LEADS:
 c=cases_for(lead,lakes,rows,ev,wb)
 if len(c)<300 or len(set(x['lakecode'] for x in c))<30:raise RuntimeError(f'lead {lead}: insufficient cases {len(c)}')
 results[str(lead)]=fit(c)
out={'version':1,'question':'Does seasonal temperature physics improve a strictly historical regional-analog baseline?','ice_source':'NSIDC G01377','weather_source':'NASA POWER daily T2M UTC','validation':'Regional baseline excludes target lake and uses neighbor observations only from years before each case; weather anomalies use prior years; GroupKFold holds out whole target lakes.','selected_lakes':len(lakes),'weather_lakes':len(wb),'weather_failures':fails,'lead_days':LEADS,'results':results,'deployment_rule':'Regional lakes may use seasonal physics only at lead times with passes=true. Use the regional-plus-physics coefficients from this report, not the direct-history coefficients.'}
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out,indent=2))
