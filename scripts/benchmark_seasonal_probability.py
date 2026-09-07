#!/usr/bin/env python3
"""Calibrate probability curves after seasonal-physics median corrections.

Direct-history lakes: tune empirical-CDF smoothing after an out-of-sample seasonal shift.
Regional-history lakes: tune logistic scale after a strictly historical regional baseline +
out-of-sample seasonal shift.

All regression predictions hold out whole lakes. Probability hyperparameters are selected
on a deterministic 80% lake subset and reported on the untouched 20% lake subset.
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
OUT=Path('north-america/data/seasonal-physics/probability-calibration.json')
NSIDC='https://noaadata.apps.nsidc.org/NOAA/G01377/liag_freeze_thaw_table.csv'
POWER='https://power.larc.nasa.gov/api/temporal/daily/point'
START_YEAR=1982;END_YEAR=2025;MAX_LAKES=100;LEADS=[45,30,21,14,7];OFFSETS=[-20,-15,-10,-5,0,5,10,15,20]
D={'shallow':-4,'medium':0,'deep':4,'verydeep':8};A={'small':-2,'medium':0,'large':2,'huge':5}

def clamp(v,a,b):return max(a,min(b,v))
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
def regional_baseline(target,year,rows,ev):
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
def temp_anom(w,year,cut):
 cur=feature(w,year,cut)
 if not cur:return None
 hist=[]
 for py in range(max(1982,year-20),year):
  f=feature(w,py,cut)
  if f:hist.append(f)
 if len(hist)<8:return None
 hm={k:statistics.median([x[k] for x in hist]) for k in ['fdd','tdd','last14','warm14']}
 return [(cur['fdd']-hm['fdd'])/100,(cur['tdd']-hm['tdd'])/50,cur['last14']-hm['last14'],(cur['warm14']-hm['warm14'])/50]
def build_cases(lead,lakes,rows,ev,wb,family):
 out=[]
 for h in lakes:
  code=h['lakecode'];w=wb.get(code)
  if not w:continue
  for year in sorted(y for y in ev[code] if START_YEAR<=y<=END_YEAR):
   prior=[d for yy,d in ev[code].items() if yy<year]
   if len(prior)<10:continue
   if family=='direct':base=float(statistics.median(prior));history=prior
   else:
    base=regional_baseline(h,year,rows,ev);history=None
    if base is None:continue
   x=temp_anom(w,year,base-lead)
   if x is None:continue
   out.append({'lakecode':code,'year':year,'base':base,'obs':float(ev[code][year]),'resid':float(ev[code][year]-base),'x':x,'history':history})
 return out
def oos_predictions(cases):
 X=np.array([c['x'] for c in cases],float);y=np.array([c['resid'] for c in cases],float);g=np.array([c['lakecode'] for c in cases]);pred=np.zeros(len(y))
 for tr,te in GroupKFold(min(8,len(set(g)))).split(X,y,g):
  m=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=12.0))]);m.fit(X[tr],y[tr]);pred[te]=m.predict(X[te])
 return pred
def sigmoid(x):
 if x>=0:return 1/(1+math.exp(-min(x,60)))
 e=math.exp(max(x,-60));return e/(1+e)
def direct_prob(history,target,corr,smooth):return sum(sigmoid((target-corr-d)/smooth) for d in history)/len(history)
def logistic_prob(target,median,scale):return sigmoid((target-median)/scale)
def lake_test(code):return int(hashlib.sha1(code.encode()).hexdigest()[:8],16)%5==0
def pm(y,p):
 p=min(.999999,max(.000001,p));return (p-y)**2,-(y*math.log(p)+(1-y)*math.log(1-p))
def prob_metrics(rows):
 if not rows:return {'n':0}
 bs=[];ll=[];bins=[[] for _ in range(10)]
 for y,p in rows:
  b,l=pm(y,p);bs.append(b);ll.append(l);bins[min(9,int(p*10))].append((y,p))
 ece=sum(len(b)/len(rows)*abs(statistics.mean(y for y,_ in b)-statistics.mean(p for _,p in b)) for b in bins if b)
 return {'n':len(rows),'brier':round(statistics.mean(bs),5),'log_loss':round(statistics.mean(ll),5),'ece10':round(ece,5)}
def evaluate_direct(cases,pred,smooth,physics=True,test=None):
 rows=[]
 for i,c in enumerate(cases):
  if test is not None and lake_test(c['lakecode'])!=test:continue
  corr=float(pred[i]) if physics else 0
  for off in OFFSETS:
   target=c['base']+off;y=1 if c['obs']<=target else 0;p=direct_prob(c['history'],target,corr,smooth);rows.append((y,p))
 return prob_metrics(rows)
def evaluate_regional(cases,pred,scale,physics=True,test=None):
 rows=[]
 for i,c in enumerate(cases):
  if test is not None and lake_test(c['lakecode'])!=test:continue
  med=c['base']+(float(pred[i]) if physics else 0)
  for off in OFFSETS:
   target=c['base']+off;y=1 if c['obs']<=target else 0;p=logistic_prob(target,med,scale);rows.append((y,p))
 return prob_metrics(rows)

summary=json.loads(HIST.read_text());rows=[h for h in summary['lakes'] if h.get('records',0)>=10];ev=events();lakes=select(summary,ev);wb={};fails=[]
with ThreadPoolExecutor(max_workers=3) as ex:
 fs={ex.submit(weather,h):h for h in lakes}
 for f in as_completed(fs):
  h=fs[f]
  try:k,w=f.result();wb[k]=w
  except Exception as e:fails.append({'lakecode':h['lakecode'],'error':str(e)})
if len(wb)<80:raise RuntimeError(f'Insufficient POWER coverage {len(wb)}/{len(lakes)}')
out={'version':1,'ice_source':'NSIDC G01377','weather_source':'NASA POWER daily T2M UTC','validation':'Whole-lake OOS physics predictions; probability smoothing/scale selected on deterministic 80% lakes and evaluated on untouched 20% lakes.','offsets_days':OFFSETS,'direct':{},'regional':{},'weather_failures':fails}
for lead in LEADS:
 dc=build_cases(lead,lakes,rows,ev,wb,'direct');dp=oos_predictions(dc);smooths=[2,3,4,5,6,8]
 train={str(s):evaluate_direct(dc,dp,s,True,False) for s in smooths};best=min(smooths,key=lambda s:train[str(s)]['brier']);test=evaluate_direct(dc,dp,best,True,True);base=evaluate_direct(dc,dp,3,False,True)
 out['direct'][str(lead)]={'cases':len(dc),'lakes':len(set(c['lakecode'] for c in dc)),'candidate_smoothing_days':smooths,'train_physics':train,'selected_smoothing_days':best,'heldout_baseline_empirical_smooth3':base,'heldout_physics':test,'relative_brier_improvement':round((base['brier']-test['brier'])/base['brier'],4),'passes':bool(test['brier']<base['brier'] and test['ece10']<=.06)}
 rc=build_cases(lead,lakes,rows,ev,wb,'regional');rp=oos_predictions(rc);scales=[4.5,5.5,6.5,7.5,8.5,10,12]
 rtrain={str(s):evaluate_regional(rc,rp,s,True,False) for s in scales};rbest=min(scales,key=lambda s:rtrain[str(s)]['brier']);rtest=evaluate_regional(rc,rp,rbest,True,True);rbase=evaluate_regional(rc,rp,6.5,False,True)
 out['regional'][str(lead)]={'cases':len(rc),'lakes':len(set(c['lakecode'] for c in rc)),'candidate_scales_days':scales,'train_physics':rtrain,'selected_scale_days':rbest,'heldout_baseline_scale6_5':rbase,'heldout_physics':rtest,'relative_brier_improvement':round((rbase['brier']-rtest['brier'])/rbase['brier'],4),'passes':bool(rtest['brier']<rbase['brier'] and rtest['ece10']<=.06)}
out['deployment_rule']='Use lead-specific direct empirical smoothing and regional logistic scale only where passes=true; interpolate probability parameters between adjacent passing lead models.'
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out,indent=2))
