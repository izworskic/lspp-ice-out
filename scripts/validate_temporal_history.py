#!/usr/bin/env python3
import csv, io, json, math, statistics, urllib.request
from collections import defaultdict
from pathlib import Path

URL='https://noaadata.apps.nsidc.org/NOAA/G01377/liag_freeze_thaw_table.csv'
OUT=Path('north-america/data/ice-history/temporal-validation.json')

def median(xs): return statistics.median(xs)
def linear_predict(points, year, slope_cap=0.6):
    if len(points)<8: return None
    xs=[p[0] for p in points]; ys=[p[1] for p in points]
    mx=sum(xs)/len(xs); my=sum(ys)/len(ys)
    den=sum((x-mx)**2 for x in xs)
    if den<=0:return my
    slope=sum((x-mx)*(y-my) for x,y in points)/den
    slope=max(-slope_cap,min(slope_cap,slope))
    return my+slope*(year-mx)
def metrics(errs):
    ae=sorted(abs(e) for e in errs)
    if not ae:return {'n':0}
    def pct(p):return ae[min(len(ae)-1,round((len(ae)-1)*p))]
    return {'n':len(errs),'mae':round(statistics.mean(ae),3),'median_abs_error':round(statistics.median(ae),3),'p80_abs_error':round(pct(.8),3),'p90_abs_error':round(pct(.9),3),'bias_days':round(statistics.mean(errs),3)}

def parse():
    raw=urllib.request.urlopen(URL,timeout=60).read().decode('utf-8-sig')
    rows=csv.DictReader(io.StringIO(raw)); by=defaultdict(list); names={}
    allowed={'CANADA','UNITED STATES','USA','UNITED STATES OF AMERICA'}
    for r in rows:
        if r.get('lakeorriver','').strip().upper()!='L':continue
        if r.get('country','').strip().upper() not in allowed:continue
        try:
            y=int(r['iceoff_year']);m=int(r['iceoff_month']);d=int(r['iceoff_day'])
            if y<1900 or m<1 or d<1:continue
            import datetime as dt
            doy=dt.date(y,m,d).timetuple().tm_yday
        except:continue
        code=r['lakecode'].strip(); names[code]=r.get('lakename','').strip()
        by[code].append((y,doy))
    return by,names

by,names=parse()
methods={'prior_all_median':[],'prior_15yr_median':[],'trend_projection':[],'blend_recent_trend':[]}
lake_counts=defaultdict(int); examples=[]
for code,vals in by.items():
    # collapse duplicate observations for same lake/year by median
    yr=defaultdict(list)
    for y,d in vals:yr[y].append(d)
    series=sorted((y,median(ds)) for y,ds in yr.items())
    if len(series)<15:continue
    for i,(test_year,obs) in enumerate(series):
        prior=series[:i]
        if len(prior)<10:continue
        allmed=median([d for _,d in prior])
        recent=[d for y,d in prior if y>=test_year-15]
        recmed=median(recent) if len(recent)>=5 else allmed
        trend=linear_predict(prior,test_year)
        blend=0.65*recmed+0.35*(trend if trend is not None else recmed)
        preds={'prior_all_median':allmed,'prior_15yr_median':recmed,'trend_projection':trend if trend is not None else allmed,'blend_recent_trend':blend}
        for k,p in preds.items():methods[k].append(p-obs)
        lake_counts[code]+=1
        if len(examples)<5000:examples.append({'lakecode':code,'lake':names.get(code,''),'year':test_year,'observed':obs,'all_median':round(allmed,1),'recent15':round(recmed,1),'trend':round(preds['trend_projection'],1),'blend':round(blend,1)})

summary={k:metrics(v) for k,v in methods.items()}
best=min(summary,key=lambda k:summary[k].get('mae',999))
out={'method':'rolling-origin temporal validation; each test year uses only earlier observations from that lake','source':'NSIDC G01377','eligible_lakes':len(lake_counts),'test_cases':sum(lake_counts.values()),'metrics':summary,'best_by_mae':best,'notes':['Trend slope is clipped to +/-0.6 days/year to limit extrapolation.','Recent median uses preceding 15 calendar years when at least five observations exist.','Blend = 65% recent median + 35% clipped trend projection.']}
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
print(json.dumps(out,indent=2))
