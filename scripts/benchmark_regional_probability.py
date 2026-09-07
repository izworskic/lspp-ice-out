#!/usr/bin/env python3
import csv, datetime as dt, hashlib, io, json, math, statistics, urllib.request
from collections import defaultdict
from pathlib import Path

CAL=Path('north-america/data/ice-history/nsidc-calibration.json')
OUT=Path('north-america/data/ice-history/regional-probability-validation.json')
RAW='https://noaadata.apps.nsidc.org/NOAA/G01377/liag_freeze_thaw_table.csv'
OFFSETS=[-25,-20,-15,-10,-5,0,5,10,15,20,25]
SCALES=[4.5,5.5,6.5,7.5,8.5,9.5,10.5,12.0,14.0]
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
def regional_pred(target,rows):
    nearby=[]
    for h in rows:
        if h['lakecode']==target['lakecode'] or h['country']!=target['country'] or h['records']<15:continue
        d=hav(target,h)
        if d<=500:nearby.append((d,h))
    nearby.sort(key=lambda x:x[0]);nearby=nearby[:16]
    if len(nearby)<3:return None
    num=den=0
    for d,h in nearby:
        residual=h['median_doy']-baseline(h);w=math.sqrt(h['records'])*math.exp(-d/220);num+=residual*w;den+=w
    return round(baseline(target)+clamp(num/den,-15,15)) if den else None
def logistic(z):return 1/(1+math.exp(-max(-35,min(35,z))))
def ece(rows,bins=10):
    n=len(rows);total=0
    for b in range(bins):
        lo=b/bins;hi=(b+1)/bins;q=[r for r in rows if lo<=r[0]<(hi if b<bins-1 else hi+1e-9)]
        if q:total+=len(q)/n*abs(statistics.mean(x[0] for x in q)-statistics.mean(x[1] for x in q))
    return total
def metrics(rows):
    return {'n':len(rows),'brier':round(statistics.mean((p-y)**2 for p,y in rows),5),'ece10':round(ece(rows),5)}
def load_events():
    text=urllib.request.urlopen(RAW,timeout=90).read().decode('utf-8-sig');by=defaultdict(lambda:defaultdict(list));allowed={'CANADA','UNITED STATES','USA','UNITED STATES OF AMERICA'}
    for r in csv.DictReader(io.StringIO(text)):
        if r.get('lakeorriver','').strip().upper()!='L' or r.get('country','').strip().upper() not in allowed:continue
        try:y=int(r['iceoff_year']);d=dt.date(y,int(r['iceoff_month']),int(r['iceoff_day'])).timetuple().tm_yday
        except:continue
        if y>=1950:by[r['lakecode'].strip()][y].append(d)
    return {k:[statistics.median(v) for _,v in sorted(years.items())] for k,years in by.items()}

rows=[h for h in json.loads(CAL.read_text())['lakes'] if h['records']>=15]
events=load_events();sets={'train':defaultdict(list),'test':defaultdict(list)};lakes={'train':0,'test':0}
for h in rows:
    pred=regional_pred(h,rows);obs=events.get(h['lakecode'],[])
    if pred is None or len(obs)<10:continue
    split='test' if int(hashlib.sha1(h['lakecode'].encode()).hexdigest()[:8],16)%5==0 else 'train';lakes[split]+=1
    for actual in obs:
        for off in OFFSETS:
            target=pred+off;y=1 if actual<=target else 0
            for scale in SCALES:sets[split][str(scale)].append((logistic((target-pred)/scale),y))
train_metrics={s:metrics(v) for s,v in sets['train'].items()};best=min(train_metrics,key=lambda s:train_metrics[s]['brier'])
test_metrics={s:metrics(v) for s,v in sets['test'].items()}
out={'method':'regional leave-one-lake prediction; scale chosen on deterministic 80% lake train split and evaluated on held-out 20% lakes','source':'NSIDC G01377','offsets':OFFSETS,'candidate_scales_days':SCALES,'train_lakes':lakes['train'],'test_lakes':lakes['test'],'train_metrics':train_metrics,'selected_scale_days':float(best),'heldout_test_metrics_selected':test_metrics[best],'heldout_test_metrics_all':test_metrics}
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out,indent=2))
