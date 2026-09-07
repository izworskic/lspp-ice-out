#!/usr/bin/env python3
"""Validate temperature-physics residual models at multiple lead times before normal ice-out."""
import csv, datetime as dt, io, json, math, statistics, time, urllib.parse, urllib.request, urllib.error
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

HIST=Path('north-america/data/ice-history/nsidc-calibration.json')
OUT=Path('north-america/data/seasonal-physics/lead-models.json')
NSIDC='https://noaadata.apps.nsidc.org/NOAA/G01377/liag_freeze_thaw_table.csv'
POWER='https://power.larc.nasa.gov/api/temporal/daily/point'
START_YEAR=1982;END_YEAR=2025;MAX_LAKES=100;LEADS=[45,30,21,14,7]

def pct(xs,p):
 s=sorted(xs);return s[min(len(s)-1,round((len(s)-1)*p))] if s else None
def metrics(errs):
 ae=[abs(float(x)) for x in errs]
 return {'n':len(ae),'mae':round(statistics.mean(ae),3),'median_abs_error':round(statistics.median(ae),3),'p80_abs_error':round(pct(ae,.8),3),'p90_abs_error':round(pct(ae,.9),3),'bias_days':round(statistics.mean(float(x) for x in errs),3)} if ae else {'n':0}
def fetch_json(url,tries=3):
 last=None
 for i in range(tries):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'chrisizworski-ice-out/1.0'})
   with urllib.request.urlopen(req,timeout=120) as r:return json.loads(r.read().decode())
  except urllib.error.HTTPError as e:
   try:detail=e.read().decode('utf-8','replace')[:500]
   except:detail=''
   last=RuntimeError(f'HTTP {e.code}: {detail}')
   if e.code==422:break
   time.sleep(2*(i+1))
  except Exception as e:last=e;time.sleep(2*(i+1))
 raise last
def events():
 raw=urllib.request.urlopen(NSIDC,timeout=90).read().decode('utf-8-sig');by=defaultdict(lambda:defaultdict(list));allowed={'CANADA','UNITED STATES','USA','UNITED STATES OF AMERICA'}
 for r in csv.DictReader(io.StringIO(raw)):
  if r.get('lakeorriver','').strip().upper()!='L' or r.get('country','').strip().upper() not in allowed:continue
  try:y=int(r['iceoff_year']);d=dt.date(y,int(r['iceoff_month']),int(r['iceoff_day'])).timetuple().tm_yday
  except:continue
  if y>=1900:by[r['lakecode'].strip()][y].append(d)
 return {k:{y:statistics.median(ds) for y,ds in v.items()} for k,v in by.items()}
def select(summary,ev):
 c=[]
 for h in summary['lakes']:
  recent=sum(1 for y in ev.get(h['lakecode'],{}) if START_YEAR<=y<=END_YEAR)
  if h.get('records',0)>=20 and recent>=10 and 41<=float(h['lat'])<=72:c.append((recent,h))
 c.sort(key=lambda z:(-z[0],-z[1]['records']));out=[];seen=set()
 for _,h in c:
  cell=(math.floor(h['lat']/2),math.floor(h['lon']/2))
  if cell in seen:continue
  seen.add(cell);out.append(h)
  if len(out)>=MAX_LAKES:break
 have={h['lakecode'] for h in out}
 for _,h in c:
  if len(out)>=MAX_LAKES:break
  if h['lakecode'] not in have:out.append(h);have.add(h['lakecode'])
 return out
def url(h):
 q={'parameters':'T2M','community':'AG','longitude':h['lon'],'latitude':h['lat'],'start':'19810101','end':f'{END_YEAR}1231','format':'JSON','time-standard':'UTC'}
 return POWER+'?'+urllib.parse.urlencode(q)
def weather(h):
 j=fetch_json(url(h));p=j.get('properties',{}).get('parameter',{}).get('T2M',{});o={}
 for k,v in p.items():
  try:d=dt.datetime.strptime(k,'%Y%m%d').date();v=float(v)
  except:continue
  if v>-900:o[d]=v
 if len(o)<1000:raise RuntimeError(f'too little POWER data {len(o)}')
 return h['lakecode'],o
def feature(w,year,cutoff):
 end=dt.date(year,1,1)+dt.timedelta(days=int(round(cutoff))-1);start=dt.date(year-1,11,1)
 vals=[];d=start
 while d<=end:
  if d in w:vals.append((d,w[d]))
  d+=dt.timedelta(days=1)
 expected=(end-start).days+1
 if expected<=0 or len(vals)<expected*.9:return None
 fdd=sum(max(0,-t) for _,t in vals);jan=dt.date(year,1,1);tdd=sum(max(0,t) for d,t in vals if d>=jan)
 last=[t for d,t in vals if d>end-dt.timedelta(days=14)]
 if len(last)<10:return None
 return {'fdd':fdd,'tdd':tdd,'last14':statistics.mean(last),'warm14':sum(max(0,t) for d,t in vals if d>end-dt.timedelta(days=14))}
def cases_for(lead,lakes,ev,wb):
 out=[]
 for h in lakes:
  code=h['lakecode'];w=wb.get(code)
  if not w:continue
  for y in sorted(y for y in ev[code] if START_YEAR<=y<=END_YEAR):
   prior=[ev[code][py] for py in ev[code] if py<y]
   if len(prior)<10:continue
   med=statistics.median(prior);cut=med-lead;cur=feature(w,y,cut)
   if not cur:continue
   hist=[]
   for py in range(max(1982,y-20),y):
    f=feature(w,py,cut)
    if f:hist.append(f)
   if len(hist)<8:continue
   hm={k:statistics.median([x[k] for x in hist]) for k in ['fdd','tdd','last14','warm14']}
   x=[(cur['fdd']-hm['fdd'])/100,(cur['tdd']-hm['tdd'])/50,cur['last14']-hm['last14'],(cur['warm14']-hm['warm14'])/50]
   out.append({'lakecode':code,'resid':float(ev[code][y]-med),'x':x})
 return out
def fit(cases):
 X=np.array([c['x'] for c in cases]);y=np.array([c['resid'] for c in cases]);g=np.array([c['lakecode'] for c in cases]);pred=np.zeros(len(y));folds=min(8,len(set(g)))
 for tr,te in GroupKFold(folds).split(X,y,g):
  m=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=12.0))]);m.fit(X[tr],y[tr]);pred[te]=m.predict(X[te])
 base=-y;err=pred-y;full=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=12.0))]);full.fit(X,y);sc=full.named_steps['scale'];rg=full.named_steps['ridge']
 bm=metrics(base);pm=metrics(err);rel=(bm['mae']-pm['mae'])/bm['mae']
 return {'cases':len(cases),'lakes':len(set(g)),'baseline':bm,'physics':pm,'relative_mae_improvement':round(rel,4),'improved_fraction':round(sum(abs(err[i])<abs(base[i]) for i in range(len(y)))/len(y),4),'passes':bool(rel>=.08 and pm['mae']<=7.5),'model':{'feature_order':['fdd_anom_per_100Cday','tdd_anom_per_50Cday','last14_temp_anom_C','warm14_anom_per_50Cday'],'mean':[round(float(v),6) for v in sc.mean_],'scale':[round(float(v),6) for v in sc.scale_],'coef_scaled':[round(float(v),6) for v in rg.coef_],'intercept':round(float(rg.intercept_),6),'alpha':12.0}}

summary=json.loads(HIST.read_text());ev=events();lakes=select(summary,ev);wb={};fails=[]
with ThreadPoolExecutor(max_workers=4) as ex:
 fs={ex.submit(weather,h):h for h in lakes}
 for f in as_completed(fs):
  h=fs[f]
  try:k,w=f.result();wb[k]=w
  except Exception as e:fails.append({'lakecode':h['lakecode'],'error':str(e)})
if len(wb)<80:raise RuntimeError(f'Insufficient POWER coverage: {len(wb)}/{len(lakes)}')
results={}
for lead in LEADS:
 c=cases_for(lead,lakes,ev,wb)
 if len(c)<300 or len(set(x['lakecode'] for x in c))<30:raise RuntimeError(f'lead {lead}: insufficient cases')
 results[str(lead)]=fit(c)
out={'version':1,'source_ice':'NSIDC G01377','source_weather':'NASA POWER daily T2M UTC','validation':'rolling-origin lake histories plus GroupKFold holding out whole lakes','selected_lakes':len(lakes),'weather_lakes_succeeded':len(wb),'weather_failures':fails,'lead_days':LEADS,'results':results,'deployment_rule':'Only use a lead model where passes=true. Interpolate model-predicted residual corrections between adjacent passing lead models; do not extrapolate beyond 45 or inside 7 days without a separate observational/satellite layer.'}
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out,indent=2))
