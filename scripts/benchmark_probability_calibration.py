#!/usr/bin/env python3
import csv, datetime as dt, io, json, math, statistics, urllib.request
from collections import defaultdict
from pathlib import Path

URL='https://noaadata.apps.nsidc.org/NOAA/G01377/liag_freeze_thaw_table.csv'
OUT=Path('north-america/data/ice-history/probability-validation.json')
OFFSETS=[-20,-15,-10,-5,0,5,10,15,20]

def logistic(z):
    if z>35:return 1.0
    if z<-35:return 0.0
    return 1/(1+math.exp(-z))
def percentile(xs,p):
    s=sorted(xs);pos=(len(s)-1)*p;lo=math.floor(pos);hi=math.ceil(pos)
    return s[lo] if lo==hi else s[lo]*(hi-pos)+s[hi]*(pos-lo)
def clip(p):return max(.001,min(.999,p))
def ece(rows,bins=10):
    out=0;n=len(rows)
    for b in range(bins):
        lo=b/bins;hi=(b+1)/bins
        q=[r for r in rows if (lo<=r[0]<hi) or (b==bins-1 and r[0]==1)]
        if not q:continue
        out+=len(q)/n*abs(statistics.mean(x[0] for x in q)-statistics.mean(x[1] for x in q))
    return out
def metrics(rows):
    return {'n':len(rows),'brier':round(statistics.mean((p-y)**2 for p,y in rows),5),'log_loss':round(statistics.mean(-(y*math.log(clip(p))+(1-y)*math.log(clip(1-p))) for p,y in rows),5),'ece10':round(ece(rows,10),5)}

def load():
    raw=urllib.request.urlopen(URL,timeout=90).read().decode('utf-8-sig');rows=csv.DictReader(io.StringIO(raw));by=defaultdict(lambda:defaultdict(list))
    allowed={'CANADA','UNITED STATES','USA','UNITED STATES OF AMERICA'}
    for r in rows:
        if r.get('lakeorriver','').strip().upper()!='L' or r.get('country','').strip().upper() not in allowed:continue
        try:y=int(r['iceoff_year']);d=dt.date(y,int(r['iceoff_month']),int(r['iceoff_day'])).timetuple().tm_yday
        except:continue
        if y<1900:continue
        by[r['lakecode'].strip()][y].append(d)
    return {k:sorted((y,statistics.median(ds)) for y,ds in v.items()) for k,v in by.items()}

def methods(prior,target):
    med=statistics.median(prior)
    p10=percentile(prior,.1);p90=percentile(prior,.9)
    generic=logistic((target-med)/5.5)
    hist_scale=max(2.5,(p90-p10)/4.394)
    width=logistic((target-med)/hist_scale)
    empirical=(sum(d<=target for d in prior)+1)/(len(prior)+2)
    smooth3=statistics.mean(logistic((target-d)/3.0) for d in prior)
    smooth5=statistics.mean(logistic((target-d)/5.0) for d in prior)
    return {'generic_logistic':generic,'history_width_logistic':width,'empirical_laplace':empirical,'empirical_smooth3':smooth3,'empirical_smooth5':smooth5}

by=load();scores=defaultdict(list);lakecases=defaultdict(int)
for code,series in by.items():
    if len(series)<15:continue
    for i,(year,obs) in enumerate(series):
        prior=[d for _,d in series[:i]]
        if len(prior)<10:continue
        med=statistics.median(prior)
        for off in OFFSETS:
            target=med+off;y=1 if obs<=target else 0
            for name,p in methods(prior,target).items():scores[name].append((p,y))
        lakecases[code]+=1
out={'method':'rolling-origin probability calibration; every test year uses only earlier observations from the same lake','source':'NSIDC G01377','eligible_lakes':len(lakecases),'test_lake_years':sum(lakecases.values()),'target_offsets_days':OFFSETS,'metrics':{k:metrics(v) for k,v in scores.items()}}
out['best_brier']=min(out['metrics'],key=lambda k:out['metrics'][k]['brier']);out['best_ece']=min(out['metrics'],key=lambda k:out['metrics'][k]['ece10'])
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out,indent=2))
