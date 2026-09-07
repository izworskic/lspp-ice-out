#!/usr/bin/env python3
"""Calibrate 50%/80% forecast intervals after seasonal-physics corrections.

Direct and regional families are calibrated separately at 45/30/21/14/7-day leads.
Physics corrections are generated out-of-sample with whole-lake GroupKFold. Interval
half-widths are selected on deterministic 80% lakes and evaluated on untouched 20% lakes.
"""
from __future__ import annotations
import csv, datetime as dt, hashlib, io, json, math, statistics, time, urllib.error, urllib.parse, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

HIST=Path('north-america/data/ice-history/nsidc-calibration.json')
OUT=Path('north-america/data/seasonal-physics/postphysics-intervals.json')
NSIDC='https://noaadata.apps.nsidc.org/NOAA/G01377/liag_freeze_thaw_table.csv'
POWER='https://power.larc.nasa.gov/api/temporal/daily/point'
START_YEAR=1982;END_YEAR=2025;MAX_LAKES=100;LEADS=[45,30,21,14,7]
D={'shallow':-4,'medium':0,'deep':4,'verydeep':8};A={'small':-2,'medium':0,'large':2,'huge':5}

def clamp(v,a,b):return max(a,min(b,v))
def percentile(xs,p):
 s=sorted(xs);pos=(len(s)-1)*p;lo=math.floor(pos);hi=math.ceil(pos);return s[lo] if lo==hi else s[lo]*(hi-pos)+s[hi]*(pos-lo)
def heldout(code):return int(hashlib.sha1(code.encode()).hexdigest()[:8],16)%5==0
def fetch_json(url,tries=4):
 last=None
 for i in range(tries):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'chrisizworski-ice-out/1.0'})
   with urllib.request.urlopen(req,timeout=120) as r:return json.loads(r.read().decode())
  except urllib.error.HTTPError as e:
   try:detail=e.read().decode('utf-8','replace')[:300]
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
def anomaly(w,year,cut):
 cur=feature(w,year,cut)
 if not cur:return None
 hist=[]
 for py in range(max(1982,year-20),year):
  f=feature(w,py,cut)
  if f:hist.append(f)
 if len(hist)<8:return None
 med={k:statistics.median([x[k] for x in hist]) for k in ['fdd','tdd','last14','warm14']}
 return [(cur['fdd']-med['fdd'])/100,(cur['tdd']-med['tdd'])/50,cur['last14']-med['last14'],(cur['warm14']-med['warm14'])/50]
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
def regional_base(target,year,rows,ev):
 near=[]
 for h in rows:
  if h['lakecode']==target['lakecode'] or h['country']!=target['country']:continue
  prior=[d for yy,d in ev.get(h['lakecode'],{}).items() if yy<year and yy>=1950]
  if len(prior)<10:continue
  dist=hav(target,h)
  if dist<=500:near.append((dist,h,statistics.median(prior),len(prior)))
 near.sort(key=lambda z:z[0]);near=near[:8]
 if len(near)<3:return None
 num=den=0
 for dist,h,med,nrec in near:
  elev=math.exp(-abs(float(target['elevation_m'])-float(h['elevation_m']))/250) if target.get('elevation_m') is not None and h.get('elevation_m') is not None else 1
  td,hd=target.get('mean_depth_m'),h.get('mean_depth_m');depth=math.exp(-abs(math.log(float(td)/float(hd)))/2) if td and hd and td>0 and hd>0 else 1
  wt=math.sqrt(nrec)*math.exp(-dist/140)*elev*depth;num+=(med-morph(h))*wt;den+=wt
 return float(clamp(morph(target)+clamp(num/den,-15,15),92,220)) if den else None
def cases(lead,family,lakes,rows,ev,wb):
 out=[]
 for h in lakes:
  w=wb.get(h['lakecode'])
  if not w:continue
  for year in sorted(y for y in ev[h['lakecode']] if START_YEAR<=y<=END_YEAR):
   prior=[d for yy,d in ev[h['lakecode']].items() if yy<year]
   if len(prior)<10:continue
   base=float(statistics.median(prior)) if family=='direct' else regional_base(h,year,rows,ev)
   if base is None:continue
   x=anomaly(w,year,base-lead)
   if x is None:continue
   out.append({'lakecode':h['lakecode'],'x':x,'resid':float(ev[h['lakecode']][year]-base)})
 return out
def oos_residuals(cs):
 X=np.array([c['x'] for c in cs],float);y=np.array([c['resid'] for c in cs],float);g=np.array([c['lakecode'] for c in cs]);pred=np.zeros(len(y))
 for tr,te in GroupKFold(min(8,len(set(g)))).split(X,y,g):
  m=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=12.0))]);m.fit(X[tr],y[tr]);pred[te]=m.predict(X[te])
 return [{'lakecode':c['lakecode'],'error':float(y[i]-pred[i])} for i,c in enumerate(cs)]
def calibrate(rows):
 train=[r['error'] for r in rows if not heldout(r['lakecode'])];test=[r['error'] for r in rows if heldout(r['lakecode'])]
 h50=percentile([abs(x) for x in train],.50);h80=percentile([abs(x) for x in train],.80);lo80=percentile(train,.10);hi80=percentile(train,.90);lo50=percentile(train,.25);hi50=percentile(train,.75)
 def cov(xs,lo,hi):return round(sum(lo<=x<=hi for x in xs)/len(xs),4)
 return {'train_n':len(train),'test_n':len(test),'symmetric_halfwidth_days':{'p50':round(h50,2),'p80':round(h80,2)},'asymmetric_offsets_days':{'p25':round(lo50,2),'p75':round(hi50,2),'p10':round(lo80,2),'p90':round(hi80,2)},'heldout_coverage':{'symmetric50':cov(test,-h50,h50),'symmetric80':cov(test,-h80,h80),'asymmetric50':cov(test,lo50,hi50),'asymmetric80':cov(test,lo80,hi80)},'heldout_median_abs_error':round(statistics.median(abs(x) for x in test),3)}

summary=json.loads(HIST.read_text());rows=[h for h in summary['lakes'] if h.get('records',0)>=10];ev=events();lakes=select(summary,ev);wb={};fails=[]
with ThreadPoolExecutor(max_workers=3) as ex:
 fs={ex.submit(weather,h):h for h in lakes}
 for f in as_completed(fs):
  h=fs[f]
  try:k,w=f.result();wb[k]=w
  except Exception as e:fails.append({'lakecode':h['lakecode'],'error':str(e)})
if len(wb)<80:raise RuntimeError(f'Insufficient POWER coverage {len(wb)}/{len(lakes)}')
out={'version':1,'validation':'Seasonal corrections are whole-lake OOS. Interval widths/offsets are selected on deterministic 80% lakes and checked on untouched 20% lakes.','direct':{},'regional':{},'weather_failures':fails}
for lead in LEADS:
 for fam in ['direct','regional']:
  cs=cases(lead,fam,lakes,rows,ev,wb)
  if len(cs)<300:raise RuntimeError(f'{fam} lead {lead}: insufficient cases')
  out[fam][str(lead)]={'cases':len(cs),'lakes':len(set(c['lakecode'] for c in cs)),**calibrate(oos_residuals(cs))}
out['deployment_rule']='Prefer asymmetric 25/75 and 10/90 offsets where held-out coverage is near 50%/80%; otherwise use symmetric half-width. Interpolate bounds between adjacent lead models.'
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out,indent=2))
