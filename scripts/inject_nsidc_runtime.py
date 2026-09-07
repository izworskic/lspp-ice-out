#!/usr/bin/env python3
from pathlib import Path

P=Path('north-america/app.js')
s=P.read_text(encoding='utf-8')

def rep(old,new):
    global s
    if old not in s: raise SystemExit(f'Anchor missing: {old[:180]}')
    s=s.replace(old,new,1)

rep("  let hydroManifest = null;\n", "  let hydroManifest = null;\n  let iceHistory = null;\n")
rep("  const HYDRO_BASE = 'data/hydrolakes';\n", "  const HYDRO_BASE = 'data/hydrolakes';\n  const HISTORY_URL = 'data/ice-history/nsidc-calibration.json';\n")

old_baseline="""  function baselineMedianDoy(lake){
    const latTerm = 85 + (lake.lat-40)*4.2;
    if(isRegional(lake)) return clamp(Math.round(latTerm),92,205);
    const elevTerm = (lake.elev||0)/100 * 0.8;
    const dAdj = depthAdj[lake.depth] || 0;
    const sAdj = sizeAdj[lake.area] || 0;
    return clamp(Math.round(latTerm + elevTerm + dAdj + sAdj), 92, 205);
  }
"""
new_baseline="""  function morphologyBaselineDoy(lake){
    const latTerm=85+(lake.lat-40)*4.2;
    if(isRegional(lake))return clamp(Math.round(latTerm),92,205);
    const elevTerm=(lake.elev||0)/100*.8,dAdj=depthAdj[lake.depth]||0,sAdj=sizeAdj[lake.area]||0;
    return clamp(Math.round(latTerm+elevTerm+dAdj+sAdj),92,205);
  }
  function baselineMedianDoy(lake){
    if(lake.history?.type==='direct')return clamp(Math.round(lake.history.medianDoy),92,220);
    let base=morphologyBaselineDoy(lake);
    if(lake.history?.type==='regional')base+=lake.history.correctionDays;
    return clamp(Math.round(base),92,220);
  }
"""
rep(old_baseline,new_baseline)

rep("    let confidence = isRegional(lake) ? 'Low' : isOfficial(lake) ? 'Moderate' : 'Moderate';\n",
"""    let confidence = lake.history?.type==='direct' && lake.history.records>=20 ? 'Moderate–high'
      : lake.history?.type==='regional' ? 'Moderate'
      : isRegional(lake) ? 'Low' : isOfficial(lake) ? 'Moderate' : 'Moderate';
""")

reason_anchor="""  function reasonFor(lake,m,target){
    const targetText = longDate(target);
"""
reason_new="""  function reasonFor(lake,m,target){
    const targetText = longDate(target);
    if(lake.history?.type==='direct'){
      const h=lake.history;
      const hist=`${h.records} observed ice-out dates (${h.firstYear}–${h.lastYear}), median ${shortDate(fromDoy(target.getFullYear(),h.medianDoy))}`;
      if(m.applyWeather)return `${lake.name} is directly calibrated to NSIDC history: ${hist}. The current 7-day thaw forecast then makes a bounded seasonal adjustment.`;
      return `${lake.name} is directly calibrated to NSIDC history: ${hist}. Live weather is shown separately outside the active spring adjustment window.`;
    }
    if(lake.history?.type==='regional'){
      const h=lake.history,sign=h.correctionDays>0?'later':'earlier';
      const txt=`${h.stationCount} nearby long-record lakes shift the morphology baseline ${Math.abs(h.correctionDays).toFixed(1)} days ${sign}`;
      if(m.applyWeather)return `Regional NSIDC calibration is active: ${txt}. The current 7-day thaw forecast is then applied as a separate bounded adjustment.`;
      return `Regional NSIDC calibration is active: ${txt}. No single nearby lake is being treated as this lake's own history.`;
    }
"""
rep(reason_anchor,reason_new)

history_runtime=r'''
  // NSIDC G01377 historical calibration: direct lake match first, regional residual second.
  async function getIceHistory(){
    if(iceHistory)return iceHistory;
    const r=await fetch(HISTORY_URL,{cache:'force-cache'}); if(!r.ok)throw new Error(`NSIDC history ${r.status}`);
    iceHistory=await r.json(); return iceHistory;
  }
  function nameKey(s){
    const stop=new Set(['lake','reservoir','pond','lac','the','of']);
    return String(s||'').toLowerCase().replace(/[^a-z0-9 ]/g,' ').split(/\s+/).filter(x=>x&&!stop.has(x)).sort().join(' ');
  }
  function histLakeObject(h){
    return {lat:Number(h.lat),lng:Number(h.lon),elev:Number(h.elevation_m)||0,depth:depthClass(Number(h.mean_depth_m)),area:areaClass(Number(h.surface_area_km2)),registry:'history'};
  }
  async function attachHistory(lake){
    if(lake.history||lake.historyAttempted)return;
    lake.historyAttempted=true;
    try{
      const data=await getIceHistory(),rows=(data.lakes||[]).filter(h=>Number.isFinite(Number(h.lat))&&Number.isFinite(Number(h.lon)));
      const lk=nameKey(lake.name),country=lake.country==='US'?'USA':'CANADA';
      const ranked=rows.filter(h=>h.country===country).map(h=>({h,d:distanceKm(lake,{lat:Number(h.lat),lng:Number(h.lon)}),same:nameKey(h.name)===lk})).sort((a,b)=>a.d-b.d);
      const direct=ranked.find(x=>(x.same&&x.d<=35)||x.d<=1.5);
      if(direct){
        const h=direct.h;
        lake.history={type:'direct',source:'NSIDC G01377',lakecode:h.lakecode,name:h.name,distanceKm:direct.d,records:Number(h.records)||0,firstYear:h.first_year,lastYear:h.last_year,medianDoy:Number(h.median_doy),p10Doy:Number(h.p10_doy),p90Doy:Number(h.p90_doy),trendDaysDecade:h.trend_days_decade};
      }else{
        const nearby=ranked.filter(x=>x.d<=500&&Number(x.h.records)>=15).slice(0,16);
        if(nearby.length>=3){
          let num=0,den=0;
          for(const x of nearby){
            const expected=morphologyBaselineDoy(histLakeObject(x.h));
            const residual=Number(x.h.median_doy)-expected;
            const w=Math.sqrt(Number(x.h.records))*Math.exp(-x.d/220);
            num+=residual*w;den+=w;
          }
          if(den>0){
            const correction=clamp(num/den,-15,15);
            lake.history={type:'regional',source:'NSIDC G01377',stationCount:nearby.length,correctionDays:correction,maxDistanceKm:Math.round(Math.max(...nearby.map(x=>x.d))),examples:nearby.slice(0,3).map(x=>x.h.name)};
          }
        }
      }
      if(state.lake.id===lake.id&&lake.history){
        if(!state.targetTouched)$('targetDate').value=fmtDate(defaultTarget(lake));
        renderModel();
      }
    }catch(e){console.warn('NSIDC historical calibration unavailable',e);}
  }

'''
rep("  // HYDROLAKES MORPHOMETRY", history_runtime+"  // HYDROLAKES MORPHOMETRY")

old_meta="""    const meta=isOfficial(lake)&&lake.enriched
      ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · HydroLAKES ${lake.areaKm2.toFixed(lake.areaKm2<10?1:0)} km² · ${lake.depthM>0?`${lake.depthM.toFixed(1)} m avg depth`:'depth unavailable'}`
      : isRegional(lake)
        ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · official lake name · regional model`
        : `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · ${lake.depth} basin · ${lake.area} lake`;
"""
new_meta="""    const historyTag=lake.history?.type==='direct'?` · ${lake.history.records} historical ice-out dates`:lake.history?.type==='regional'?` · ${lake.history.stationCount}-lake regional history calibration`:'';
    const meta=(isOfficial(lake)&&lake.enriched
      ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · HydroLAKES ${lake.areaKm2.toFixed(lake.areaKm2<10?1:0)} km² · ${lake.depthM>0?`${lake.depthM.toFixed(1)} m avg depth`:'depth unavailable'}`
      : isRegional(lake)
        ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · official lake name · regional model`
        : `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · ${lake.depth} basin · ${lake.area} lake`)+historyTag;
"""
rep(old_meta,new_meta)

rep("    $('search').value=''; $('results').classList.remove('show'); renderModel(); refreshWeather(); enrichLake(lake);\n",
    "    $('search').value=''; $('results').classList.remove('show'); renderModel(); refreshWeather(); enrichLake(lake).finally(()=>attachHistory(lake));\n")

P.write_text(s,encoding='utf-8')
print('NSIDC historical calibration runtime injected')
