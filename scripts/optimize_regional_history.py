#!/usr/bin/env python3
"""Tune regional historical residual weighting on held-out lakes.

Uses deterministic lake-level train/test split. Hyperparameters are selected only on
train lakes and reported once on held-out test lakes. Target lake never contributes to
its own correction.
"""
import hashlib, json, math, statistics
from pathlib import Path

SRC=Path('north-america/data/ice-history/nsidc-calibration.json')
OUT=Path('north-america/data/ice-history/regional-weight-validation.json')
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
def sim_penalty(t,h,elev_scale,depth_scale,area_scale):
    p=1.0
    te=t.get('elevation_m');he=h.get('elevation_m')
    if elev_scale and te is not None and he is not None:p*=math.exp(-abs(te-he)/elev_scale)
    td=t.get('mean_depth_m');hd=h.get('mean_depth_m')
    if depth_scale and td and hd and td>0 and hd>0:p*=math.exp(-abs(math.log(td/hd))/depth_scale)
    ta=t.get('surface_area_km2');ha=h.get('surface_area_km2')
    if area_scale and ta and ha and ta>0 and ha>0:p*=math.exp(-abs(math.log(ta/ha))/area_scale)
    return p
def predict(t,rows,cfg):
    near=[]
    for h in rows:
        if h['lakecode']==t['lakecode'] or h['country']!=t['country'] or h['records']<15:continue
        d=hav(t,h)
        if d<=cfg['radius']:near.append((d,h))
    near.sort(key=lambda z:z[0]);near=near[:cfg['nmax']]
    if len(near)<3:return None
    num=den=0
    for d,h in near:
        w=(h['records']**cfg['record_pow'])*math.exp(-d/cfg['dist_scale'])*sim_penalty(t,h,cfg['elev_scale'],cfg['depth_scale'],cfg['area_scale'])
        if w<1e-12:continue
        num+=(h['median_doy']-baseline(h))*w;den+=w
    if den<=0:return None
    return round(baseline(t)+clamp(num/den,-cfg['cap'],cfg['cap']))
def mae(rows,allrows,cfg):
    e=[]
    for h in rows:
        p=predict(h,allrows,cfg)
        if p is not None:e.append(abs(p-h['median_doy']))
    return statistics.mean(e) if e else 999,len(e)
def full_metrics(rows,allrows,cfg):
    es=[]
    for h in rows:
        p=predict(h,allrows,cfg)
        if p is not None:es.append(p-h['median_doy'])
    ae=sorted(abs(e) for e in es)
    def pct(p):return ae[min(len(ae)-1,round((len(ae)-1)*p))] if ae else None
    return {'n':len(es),'mae':round(statistics.mean(ae),3),'median_abs_error':round(statistics.median(ae),3),'p80_abs_error':round(pct(.8),3),'p90_abs_error':round(pct(.9),3),'bias_days':round(statistics.mean(es),3)}

rows=[h for h in json.loads(SRC.read_text())['lakes'] if h['records']>=15]
train=[];test=[]
for h in rows:
    (test if int(hashlib.sha1(h['lakecode'].encode()).hexdigest()[:8],16)%5==0 else train).append(h)
base_cfg={'radius':500,'nmax':16,'record_pow':.5,'dist_scale':220,'elev_scale':0,'depth_scale':0,'area_scale':0,'cap':15}
candidates=[]
for ds in [140,180,220,280,360]:
  for es in [0,250,500,900]:
    for dep in [0,.7,1.2,2.0]:
      for ar in [0,.8,1.5,2.5]:
        for nmax in [8,12,16]:
          cfg={'radius':500,'nmax':nmax,'record_pow':.5,'dist_scale':ds,'elev_scale':es,'depth_scale':dep,'area_scale':ar,'cap':15}
          m,n=mae(train,rows,cfg)
          if n>=len(train)*.85:candidates.append((m,cfg,n))
candidates.sort(key=lambda z:z[0]);best=candidates[0]
out={'method':'deterministic 80/20 lake holdout; tune regional residual similarity weighting on train only','train_lakes':len(train),'test_lakes':len(test),'baseline_config':base_cfg,'baseline_train':full_metrics(train,rows,base_cfg),'baseline_test':full_metrics(test,rows,base_cfg),'selected_config':best[1],'selected_train':full_metrics(train,rows,best[1]),'selected_test':full_metrics(test,rows,best[1]),'top_train_candidates':[{'mae':round(m,3),'n':n,'config':cfg} for m,cfg,n in candidates[:15]]}
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out,indent=2))
