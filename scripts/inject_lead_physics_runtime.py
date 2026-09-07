#!/usr/bin/env python3
from pathlib import Path

p=Path('north-america/app.js')
s=p.read_text(encoding='utf-8')
if 'function seasonalPhysicsCorrection(lake)' in s:
    print('Lead-aware seasonal physics runtime already present')
    raise SystemExit(0)

old="""    weather:null, weatherError:null, targetTouched:false, ndsi:false, sensor:'modis',
    searchSeq:0, nearbySeq:0, enrichSeq:0
"""
new="""    weather:null, weatherError:null, physics:null, physicsError:null, targetTouched:false, ndsi:false, sensor:'modis',
    searchSeq:0, nearbySeq:0, enrichSeq:0, physicsSeq:0
"""
if old not in s:raise SystemExit('state marker not found')
s=s.replace(old,new,1)

old="""  const HISTORY_URL = 'data/ice-history/nsidc-calibration.json';
"""
new="""  const HISTORY_URL = 'data/ice-history/nsidc-calibration.json';
  const PHYSICS_MODELS_URL = 'data/seasonal-physics/lead-models.json';
"""
if old not in s:raise SystemExit('history URL marker not found')
s=s.replace(old,new,1)

anchor="""  function weatherShiftDays(weather){
    if(!weather || !Number.isFinite(weather.tdd7)) return 0;
    return clamp((weather.tdd7-18)/7, -4, 5);
  }

"""
insert=anchor+"""  function evalPhysicsModel(model,features){
    if(!model||!Array.isArray(features)||features.length!==4)return null;
    const mean=model.mean||[],scale=model.scale||[],coef=model.coef_scaled||[];
    if(mean.length!==4||scale.length!==4||coef.length!==4)return null;
    let out=Number(model.intercept)||0;
    for(let i=0;i<4;i++){
      const z=(features[i]-Number(mean[i]))/Number(scale[i]);
      // Do not extrapolate the regression far outside its historical training domain.
      if(!Number.isFinite(z)||Math.abs(z)>4.5)return null;
      out+=Number(coef[i])*z;
    }
    return Number.isFinite(out)?out:null;
  }

  function seasonalPhysicsCorrection(lake){
    const ph=state.physics;
    if(!ph||ph.lakeId!==lake.id||lake.history?.type!=='direct'||!ph.models?.results)return null;
    const lead=baselineMedianDoy(lake)-doy(today);
    if(lead<7||lead>45)return null;
    const leads=[45,30,21,14,7];
    let upper=leads[0],lower=leads[leads.length-1];
    for(let i=0;i<leads.length;i++){
      if(lead===leads[i]){upper=lower=leads[i];break;}
      if(i<leads.length-1&&lead<leads[i]&&lead>leads[i+1]){upper=leads[i];lower=leads[i+1];break;}
    }
    const a=ph.models.results[String(upper)],b=ph.models.results[String(lower)];
    if(!a?.passes||!b?.passes)return null;
    const ca=evalPhysicsModel(a.model,ph.features),cb=evalPhysicsModel(b.model,ph.features);
    if(!Number.isFinite(ca)||!Number.isFinite(cb))return null;
    const correction=upper===lower?ca:ca+(cb-ca)*((upper-lead)/(upper-lower));
    return Number.isFinite(correction)?correction:null; // positive = later ice-out
  }

  async function refreshSeasonalPhysics(lake){
    const seq=++state.physicsSeq; state.physics=null; state.physicsError=null;
    const lead=baselineMedianDoy(lake)-doy(today);
    if(!activeSeason(today)||lake.history?.type!=='direct'||lead<7||lead>45){if(state.lake.id===lake.id)renderModel();return;}
    try{
      // Canonicalize to the meteorological grid so nearby lake requests share CDN cache entries.
      const lat=(Math.round(lake.lat/0.5)*0.5).toFixed(3),lon=(Math.round(lake.lng/0.625)*0.625).toFixed(3);
      const [mr,fr]=await Promise.all([
        fetch(PHYSICS_MODELS_URL,{cache:'force-cache'}),
        fetch(`/api/seasonal-physics?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`)
      ]);
      if(!mr.ok)throw new Error(`physics models ${mr.status}`);
      if(!fr.ok){const detail=await fr.json().catch(()=>({}));throw new Error(detail.detail||`physics features ${fr.status}`);}
      const models=await mr.json(),feat=await fr.json();
      if(seq!==state.physicsSeq||state.lake.id!==lake.id)return;
      if(!feat.active||!Array.isArray(feat.features))throw new Error('seasonal features inactive');
      state.physics={lakeId:lake.id,features:feat.features,models,asOf:feat.as_of,priorYears:feat.prior_years,source:feat.source,lead};
      renderWeather();renderModel();
    }catch(e){
      if(seq!==state.physicsSeq||state.lake.id!==lake.id)return;
      state.physicsError=e.message||'Seasonal physics unavailable';renderWeather();renderModel();
    }
  }

"""
if anchor not in s:raise SystemExit('weatherShiftDays anchor not found')
s=s.replace(anchor,insert,1)

old="""    const applyWeather = activeSeason(today) && targetDate.getFullYear()===today.getFullYear() && state.weather && state.weather.lakeId===lake.id;
    const shift = applyWeather ? weatherShiftDays(state.weather) : 0;
    const median = Math.round(base - shift);
"""
new="""    const currentSpring = activeSeason(today) && targetDate.getFullYear()===today.getFullYear();
    const physicsCorrection = currentSpring ? seasonalPhysicsCorrection(lake) : null;
    const seasonalPhysicsApplied = Number.isFinite(physicsCorrection);
    const forecastFallbackApplied = currentSpring && !seasonalPhysicsApplied && state.weather && state.weather.lakeId===lake.id;
    const forecastShift = forecastFallbackApplied ? weatherShiftDays(state.weather) : 0;
    // correctionDays is positive when breakup is shifted later. The old forecast shift is positive earlier.
    const correctionDays = seasonalPhysicsApplied ? physicsCorrection : -forecastShift;
    const median = Math.round(base + correctionDays);
"""
if old not in s:raise SystemExit('lakeModel adjustment block not found')
s=s.replace(old,new,1)

s=s.replace("targetDoy+shift-d","targetDoy-correctionDays-d",1)
s=s.replace("h.p10Doy-shift","h.p10Doy+correctionDays",1)
s=s.replace("h.p90Doy-shift","h.p90Doy+correctionDays",1)
s=s.replace("h.p25Doy-shift","h.p25Doy+correctionDays",1)
s=s.replace("h.p20Doy-shift","h.p20Doy+correctionDays",1)
s=s.replace("h.p75Doy-shift","h.p75Doy+correctionDays",1)
s=s.replace("h.p80Doy-shift","h.p80Doy+correctionDays",1)

old="""    return {base,shift,median,p10,p90,winLo,winHi,probability,confidence,applyWeather};
"""
new="""    return {base,correctionDays,physicsCorrection,forecastShift,median,p10,p90,winLo,winHi,probability,confidence,applyWeather:seasonalPhysicsApplied||forecastFallbackApplied,seasonalPhysicsApplied,forecastFallbackApplied,physicsLead:baselineMedianDoy(lake)-doy(today)};
"""
if old not in s:raise SystemExit('lakeModel return marker not found')
s=s.replace(old,new,1)

old="""      if(m.applyWeather)return `${lake.name} is directly calibrated to NSIDC history: ${hist}. The current 7-day thaw forecast then makes a bounded seasonal adjustment.`;
      return `${lake.name} is directly calibrated to NSIDC history: ${hist}. Live weather is shown separately outside the active spring adjustment window.`;
"""
new="""      if(m.seasonalPhysicsApplied){const dir=m.correctionDays>=0?'later':'earlier';return `${lake.name} is directly calibrated to NSIDC history: ${hist}. Validated season-to-date freezing/thaw physics at a ${Math.round(m.physicsLead)}-day lead shifts the current-season median ${Math.abs(m.correctionDays).toFixed(1)} days ${dir}.`;}
      if(m.forecastFallbackApplied)return `${lake.name} is directly calibrated to NSIDC history: ${hist}. Seasonal-physics features are unavailable, so the current 7-day thaw forecast is being used only as a bounded fallback adjustment.`;
      return `${lake.name} is directly calibrated to NSIDC history: ${hist}. Live weather is shown separately outside the validated seasonal-physics lead window.`;
"""
if old not in s:raise SystemExit('direct reason marker not found')
s=s.replace(old,new,1)

old="""    const used=activeSeason(today)?'model input':'off-season only';
"""
new="""    const used=activeSeason(today)?(state.physics?.lakeId===state.lake.id?'forward context · seasonal physics active':'fallback model input'):'off-season only';
"""
if old not in s:raise SystemExit('weather used marker not found')
s=s.replace(old,new,1)

old="""    $('modeNote').textContent = activeSeason(today) && target.getFullYear()===today.getFullYear()
      ? (m.applyWeather?'Live spring mode: short-range thaw forecast is adjusting the baseline.':'Spring mode: waiting for usable live forecast; climatology is carrying the result.')
      : `Off-season outlook: live weather is visible but not applied to the ${target.getFullYear()} spring estimate.`;
"""
new="""    $('modeNote').textContent = activeSeason(today) && target.getFullYear()===today.getFullYear()
      ? (m.seasonalPhysicsApplied?'Live spring mode: validated season-to-date freezing/thaw physics is adjusting the historical baseline.':m.forecastFallbackApplied?'Live spring mode: seasonal physics is unavailable, so the short-range thaw forecast is a bounded fallback.':'Spring mode: waiting for a validated seasonal signal; climatology is carrying the result.')
      : `Off-season outlook: live weather is visible but not applied to the ${target.getFullYear()} spring estimate.`;
"""
if old not in s:raise SystemExit('mode note marker not found')
s=s.replace(old,new,1)

old="""      if(state.lake.id===lake.id&&lake.history){
        if(!state.targetTouched)$('targetDate').value=fmtDate(defaultTarget(lake));
        renderModel();
      }
"""
new="""      if(state.lake.id===lake.id&&lake.history){
        if(!state.targetTouched)$('targetDate').value=fmtDate(defaultTarget(lake));
        renderModel();
        if(lake.history.type==='direct')refreshSeasonalPhysics(lake);
      }
"""
if old not in s:raise SystemExit('attach history render marker not found')
s=s.replace(old,new,1)

old="""    if(!lake)return; rememberLake(lake); ensureMarker(lake); state.lake=lake;
"""
new="""    if(!lake)return; rememberLake(lake); ensureMarker(lake); state.lake=lake; state.physics=null; state.physicsError=null; state.physicsSeq++;
"""
if old not in s:raise SystemExit('select lake marker not found')
s=s.replace(old,new,1)

p.write_text(s,encoding='utf-8')
print('Injected lead-aware direct-history seasonal physics runtime')
