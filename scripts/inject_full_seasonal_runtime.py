#!/usr/bin/env python3
from pathlib import Path
p=Path('north-america/app.js')
s=p.read_text(encoding='utf-8')
if "const REGIONAL_PHYSICS_MODELS_URL" in s:
    print('Full calibrated seasonal runtime already present');raise SystemExit(0)

s=s.replace("  const PHYSICS_MODELS_URL = 'data/seasonal-physics/lead-models.json';\n","  const PHYSICS_MODELS_URL = 'data/seasonal-physics/lead-models.json';\n  const REGIONAL_PHYSICS_MODELS_URL = 'data/seasonal-physics/regional-plus-physics.json';\n  const PHYSICS_PROBABILITY_URL = 'data/seasonal-physics/probability-calibration.json';\n  const PHYSICS_INTERVALS_URL = 'data/seasonal-physics/postphysics-intervals.json';\n",1)

start=s.index('  function seasonalPhysicsCorrection(lake){')
end=s.index('\n  async function refreshSeasonalPhysics(lake){',start)
new_func="""  function leadBracket(lead,minLead=7){
    if(lead<minLead||lead>45)return null;
    const leads=[45,30,21,14,7].filter(x=>x>=minLead);
    let upper=leads[0],lower=leads[leads.length-1];
    for(let i=0;i<leads.length;i++){
      if(lead===leads[i]){upper=lower=leads[i];break;}
      if(i<leads.length-1&&lead<leads[i]&&lead>leads[i+1]){upper=leads[i];lower=leads[i+1];break;}
    }
    const t=upper===lower?0:(upper-lead)/(upper-lower);
    return {upper,lower,t};
  }
  function interp(a,b,t){return Number(a)+(Number(b)-Number(a))*t;}
  function seasonalPhysicsCorrection(lake){
    const ph=state.physics;if(!ph||ph.lakeId!==lake.id)return null;
    const family=lake.history?.type;if(family!=='direct'&&family!=='regional')return null;
    // Direct probability calibration passed down to 14d. Regional probability passed to 7d.
    const minLead=family==='direct'?14:7,lead=baselineMedianDoy(lake)-doy(today),br=leadBracket(lead,minLead);
    if(!br)return null;
    const results=family==='direct'?ph.directModels?.results:ph.regionalModels?.results;
    const a=results?.[String(br.upper)],b=results?.[String(br.lower)];if(!a?.passes||!b?.passes)return null;
    const ca=evalPhysicsModel(a.model,ph.features),cb=evalPhysicsModel(b.model,ph.features);if(!Number.isFinite(ca)||!Number.isFinite(cb))return null;
    const correction=interp(ca,cb,br.t);return Number.isFinite(correction)?{correction,lead,family,bracket:br}:null;
  }
  function seasonalProbabilityParameter(lake,physics){
    const ph=state.physics;if(!physics||!ph?.probability)return null;const fam=physics.family,br=physics.bracket;
    const a=ph.probability?.[fam]?.[String(br.upper)],b=ph.probability?.[fam]?.[String(br.lower)];if(!a?.passes||!b?.passes)return null;
    if(fam==='direct')return {smoothing:interp(a.selected_smoothing_days,b.selected_smoothing_days,br.t)};
    return {scale:interp(a.selected_scale_days,b.selected_scale_days,br.t)};
  }
  function seasonalIntervalOffsets(lake,physics){
    const ph=state.physics;if(!physics||!ph?.intervals)return null;const fam=physics.family,br=physics.bracket;
    const a=ph.intervals?.[fam]?.[String(br.upper)],b=ph.intervals?.[fam]?.[String(br.lower)];if(!a||!b)return null;
    const aa=a.asymmetric_offsets_days,bb=b.asymmetric_offsets_days;if(!aa||!bb)return null;
    return {p10:interp(aa.p10,bb.p10,br.t),p90:interp(aa.p90,bb.p90,br.t),p25:interp(aa.p25,bb.p25,br.t),p75:interp(aa.p75,bb.p75,br.t)};
  }
"""
s=s[:start]+new_func+s[end:]

start=s.index('  async function refreshSeasonalPhysics(lake){')
end=s.index('\n  function lakeModel(lake, targetDate){',start)
new_refresh="""  async function refreshSeasonalPhysics(lake){
    const seq=++state.physicsSeq;state.physics=null;state.physicsError=null;
    const family=lake.history?.type,lead=baselineMedianDoy(lake)-doy(today),minLead=family==='direct'?14:family==='regional'?7:999;
    if(!activeSeason(today)||(family!=='direct'&&family!=='regional')||lead<minLead||lead>45){if(state.lake.id===lake.id)renderModel();return;}
    try{
      const lat=(Math.round(lake.lat/0.5)*0.5).toFixed(3),lon=(Math.round(lake.lng/0.625)*0.625).toFixed(3);
      const [dr,rr,pr,ir,fr]=await Promise.all([
        fetch(PHYSICS_MODELS_URL,{cache:'force-cache'}),fetch(REGIONAL_PHYSICS_MODELS_URL,{cache:'force-cache'}),
        fetch(PHYSICS_PROBABILITY_URL,{cache:'force-cache'}),fetch(PHYSICS_INTERVALS_URL,{cache:'force-cache'}),
        fetch(`/api/seasonal-physics?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`)
      ]);
      for(const [name,r] of [['direct models',dr],['regional models',rr],['probability',pr],['intervals',ir]])if(!r.ok)throw new Error(`${name} ${r.status}`);
      if(!fr.ok){const detail=await fr.json().catch(()=>({}));throw new Error(detail.detail||`physics features ${fr.status}`);}
      const [directModels,regionalModels,probability,intervals,feat]=await Promise.all([dr.json(),rr.json(),pr.json(),ir.json(),fr.json()]);
      if(seq!==state.physicsSeq||state.lake.id!==lake.id)return;if(!feat.active||!Array.isArray(feat.features))throw new Error('seasonal features inactive');
      state.physics={lakeId:lake.id,features:feat.features,directModels,regionalModels,probability,intervals,asOf:feat.as_of,priorYears:feat.prior_years,source:feat.source,lead};
      renderWeather();renderModel();
    }catch(e){if(seq!==state.physicsSeq||state.lake.id!==lake.id)return;state.physicsError=e.message||'Seasonal physics unavailable';renderWeather();renderModel();}
  }
"""
s=s[:start]+new_refresh+s[end:]

old="""    const physicsCorrection = currentSpring ? seasonalPhysicsCorrection(lake) : null;
    const seasonalPhysicsApplied = Number.isFinite(physicsCorrection);
    const forecastFallbackApplied = currentSpring && !seasonalPhysicsApplied && state.weather && state.weather.lakeId===lake.id;
    const forecastShift = forecastFallbackApplied ? weatherShiftDays(state.weather) : 0;
    // correctionDays is positive when breakup is shifted later. The old forecast shift is positive earlier.
    const correctionDays = seasonalPhysicsApplied ? physicsCorrection : -forecastShift;
"""
new="""    const physics = currentSpring ? seasonalPhysicsCorrection(lake) : null;
    const seasonalPhysicsApplied = Number.isFinite(physics?.correction);
    const forecastFallbackApplied = currentSpring && !seasonalPhysicsApplied && state.weather && state.weather.lakeId===lake.id;
    const forecastShift = forecastFallbackApplied ? weatherShiftDays(state.weather) : 0;
    // correctionDays is positive when breakup is shifted later. The short-range fallback is positive earlier.
    const correctionDays = seasonalPhysicsApplied ? physics.correction : -forecastShift;
"""
if old not in s:raise SystemExit('physics correction block not found')
s=s.replace(old,new,1)

old="""    // Held-out regional calibration benchmark selected a 6.5-day logistic scale.
    const scale = lake.history?.type==='regional' ? 6.5 : Math.max(4.8, spread/2.1);
    let probability;
    if(lake.history?.type==='direct' && Array.isArray(lake.history.doys) && lake.history.doys.length>=5){
      // Rolling-origin validation favors a lightly smoothed empirical CDF over a generic S-curve.
      // correctionDays is positive for a later season, so evaluate the historical CDF against target-correction.
      probability=lake.history.doys.reduce((sum,d)=>sum+1/(1+Math.exp(-(targetDoy-correctionDays-d)/3)),0)/lake.history.doys.length;
    }else{
      probability=1/(1+Math.exp(-(targetDoy-median)/scale));
    }
"""
new="""    const probParam=seasonalPhysicsApplied?seasonalProbabilityParameter(lake,physics):null;
    const scale = probParam?.scale ?? (lake.history?.type==='regional' ? 6.5 : Math.max(4.8, spread/2.1));
    let probability;
    if(lake.history?.type==='direct' && Array.isArray(lake.history.doys) && lake.history.doys.length>=5){
      const smooth=probParam?.smoothing ?? 3;
      probability=lake.history.doys.reduce((sum,d)=>sum+1/(1+Math.exp(-(targetDoy-correctionDays-d)/smooth)),0)/lake.history.doys.length;
    }else{probability=1/(1+Math.exp(-(targetDoy-median)/scale));}
"""
if old not in s:raise SystemExit('probability block not found')
s=s.replace(old,new,1)

old="""    // Held-out lake-year validation: regional residuals cover 53.3% within +/-7 days
    // and 82.4% within +/-14 days, close to the intended 50% and 80% intervals.
    if(lake.history?.type==='regional'){p10=median-14;p90=median+14;winLo=median-7;winHi=median+7;}
"""
new="""    // Without seasonal physics, retain the validated regional climatological intervals.
    if(lake.history?.type==='regional'&&!seasonalPhysicsApplied){p10=median-14;p90=median+14;winLo=median-7;winHi=median+7;}
    if(seasonalPhysicsApplied){
      const ints=seasonalIntervalOffsets(lake,physics);
      if(ints){p10=Math.round(median+ints.p10);p90=Math.round(median+ints.p90);winLo=Math.round(median+ints.p25);winHi=Math.round(median+ints.p75);}
    }
"""
if old not in s:raise SystemExit('regional interval block not found')
s=s.replace(old,new,1)

old="""    return {base,correctionDays,physicsCorrection,forecastShift,median,p10,p90,winLo,winHi,probability,confidence,applyWeather:seasonalPhysicsApplied||forecastFallbackApplied,seasonalPhysicsApplied,forecastFallbackApplied,physicsLead:baselineMedianDoy(lake)-doy(today)};
"""
new="""    return {base,correctionDays,physicsCorrection:physics?.correction??null,forecastShift,median,p10,p90,winLo,winHi,probability,confidence,applyWeather:seasonalPhysicsApplied||forecastFallbackApplied,seasonalPhysicsApplied,forecastFallbackApplied,physicsLead:physics?.lead??(baselineMedianDoy(lake)-doy(today)),physicsFamily:physics?.family??null};
"""
if old not in s:raise SystemExit('return block not found')
s=s.replace(old,new,1)

old="""      if(m.applyWeather)return `Regional NSIDC calibration is active: ${txt}. The current 7-day thaw forecast is then applied as a separate bounded adjustment.`;
      return `Regional NSIDC calibration is active: ${txt}. No single nearby lake is being treated as this lake's own history.`;
"""
new="""      if(m.seasonalPhysicsApplied){const dir=m.correctionDays>=0?'later':'earlier';return `Regional NSIDC calibration is active: ${txt}. A separately validated regional seasonal-physics model at ${Math.round(m.physicsLead)} days lead shifts this year's median ${Math.abs(m.correctionDays).toFixed(1)} days ${dir}.`;}
      if(m.forecastFallbackApplied)return `Regional NSIDC calibration is active: ${txt}. Seasonal physics is unavailable, so the current 7-day thaw forecast is used only as a bounded fallback.`;
      return `Regional NSIDC calibration is active: ${txt}. No single nearby lake is being treated as this lake's own history.`;
"""
if old not in s:raise SystemExit('regional reason block not found')
s=s.replace(old,new,1)

old="""        if(lake.history.type==='direct')refreshSeasonalPhysics(lake);
"""
new="""        if(lake.history.type==='direct'||lake.history.type==='regional')refreshSeasonalPhysics(lake);
"""
if old not in s:raise SystemExit('refresh family marker not found')
s=s.replace(old,new,1)

p.write_text(s,encoding='utf-8');print('Injected fully calibrated direct + regional seasonal runtime')
