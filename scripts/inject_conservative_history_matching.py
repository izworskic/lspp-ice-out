#!/usr/bin/env python3
from pathlib import Path
p=Path('north-america/app.js');s=p.read_text(encoding='utf-8')
if 'function historyAreaAgreement(lake,h)' in s:
    print('Conservative history matching already applied');raise SystemExit(0)
needle="""  function histLakeObject(h){
    return {lat:Number(h.lat),lng:Number(h.lon),elev:Number(h.elevation_m)||0,depth:depthClass(Number(h.mean_depth_m)),area:areaClass(Number(h.surface_area_km2)),registry:'history'};
  }
"""
insert=needle+"""  function historyAreaAgreement(lake,h,maxRatio=2.5){
    const a=Number(lake.areaKm2),b=Number(h.surface_area_km2);
    if(!(a>0)||!(b>0))return false;
    return Math.max(a,b)/Math.min(a,b)<=maxRatio;
  }
  function chooseDirectHistory(lake,ranked){
    // Prefer false negatives over false positives: attaching another lake's history is worse
    // than falling back to the validated regional model.
    const byName=ranked.filter(x=>x.same&&x.d<=35);
    let hit=byName.find(x=>x.d<=15);
    if(!hit)hit=byName.find(x=>x.d<=35&&historyAreaAgreement(lake,x.h,2.5));
    if(hit)return {...hit,matchMethod:hit.d<=15?'name+distance':'name+distance+area'};
    hit=ranked.find(x=>x.d<=.35);
    if(hit)return {...hit,matchMethod:'near-exact-coordinate'};
    hit=ranked.find(x=>x.d<=1.0&&historyAreaAgreement(lake,x.h,2.0));
    return hit?{...hit,matchMethod:'coordinate+area'}:null;
  }
"""
if needle not in s:raise SystemExit('history helper marker not found')
s=s.replace(needle,insert,1)
old="""      const direct=ranked.find(x=>(x.same&&x.d<=35)||x.d<=1.5);
      if(direct){
        const h=direct.h;
        lake.history={type:'direct',source:'NSIDC G01377',lakecode:h.lakecode,name:h.name,distanceKm:direct.d,records:Number(h.records)||0,firstYear:h.first_year,lastYear:h.last_year,medianDoy:Number(h.median_doy),p10Doy:Number(h.p10_doy),p20Doy:Number(h.p20_doy),p25Doy:Number(h.p25_doy),p75Doy:Number(h.p75_doy),p80Doy:Number(h.p80_doy),p90Doy:Number(h.p90_doy),doys:Array.isArray(h.iceout_doys)?h.iceout_doys.map(Number).filter(Number.isFinite):[],trendDaysDecade:h.trend_days_decade};
"""
new="""      const direct=chooseDirectHistory(lake,ranked);
      if(direct){
        const h=direct.h;
        lake.history={type:'direct',source:'NSIDC G01377',lakecode:h.lakecode,name:h.name,distanceKm:direct.d,matchMethod:direct.matchMethod,records:Number(h.records)||0,firstYear:h.first_year,lastYear:h.last_year,medianDoy:Number(h.median_doy),p10Doy:Number(h.p10_doy),p20Doy:Number(h.p20_doy),p25Doy:Number(h.p25_doy),p75Doy:Number(h.p75_doy),p80Doy:Number(h.p80_doy),p90Doy:Number(h.p90_doy),doys:Array.isArray(h.iceout_doys)?h.iceout_doys.map(Number).filter(Number.isFinite):[],trendDaysDecade:h.trend_days_decade};
"""
if old not in s:raise SystemExit('direct history match block not found')
s=s.replace(old,new,1);p.write_text(s,encoding='utf-8');print('Applied conservative direct-history matching')
