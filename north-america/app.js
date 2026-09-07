(() => {
  const benchmarkLakes = window.ICEOUT_LAKES || [];
  const $ = id => document.getElementById(id);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const activeSeason = (d=today) => d.getMonth() >= 1 && d.getMonth() <= 6;
  const nextSpringYear = now.getMonth() >= 7 ? now.getFullYear()+1 : now.getFullYear();
  const dynamicLakes = new Map();
  const hydrolakesCache = new Map();
  let hydroManifest = null;
  let iceHistory = null;
  const state = {
    lake: benchmarkLakes.find(x=>x.id==='lake-vermilion-mn') || benchmarkLakes[0],
    weather:null, weatherError:null, physics:null, physicsError:null, targetTouched:false, ndsi:false, sensor:'modis',
    searchSeq:0, nearbySeq:0, enrichSeq:0, physicsSeq:0
  };

  const depthAdj = {shallow:-4, medium:0, deep:4, verydeep:8};
  const sizeAdj = {small:-2, medium:0, large:2, huge:5};
  const US_GNIS = 'https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer/7/query';
  const CA_NAMES = 'https://geogratis.gc.ca/services/geoname/en/geonames.json';
  const HYDRO_BASE = 'data/hydrolakes';
  const HISTORY_URL = 'data/ice-history/nsidc-calibration.json';
  const PHYSICS_MODELS_URL = 'data/seasonal-physics/lead-models.json';
  const REGIONAL_PHYSICS_MODELS_URL = 'data/seasonal-physics/regional-plus-physics.json';
  const PHYSICS_PROBABILITY_URL = 'data/seasonal-physics/probability-calibration.json';
  const PHYSICS_INTERVALS_URL = 'data/seasonal-physics/postphysics-intervals.json';

  function clamp(v,a,b){return Math.max(a,Math.min(b,v));}
  function fmtDate(d){return d.toISOString().slice(0,10);}
  function doy(d){const y=d.getFullYear(); return Math.floor((Date.UTC(y,d.getMonth(),d.getDate())-Date.UTC(y,0,0))/86400000);}
  function fromDoy(year,n){const d=new Date(year,0,1); d.setDate(n); return d;}
  function shortDate(d){return d.toLocaleDateString('en-US',{month:'short',day:'numeric'});}
  function longDate(d){return d.toLocaleDateString('en-US',{month:'long',day:'numeric'});}
  function escapeHtml(s){return String(s??'').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
  function distanceKm(a,b){
    const R=6371, p=Math.PI/180;
    const dLat=(b.lat-a.lat)*p,dLon=(b.lng-a.lng)*p;
    const s=Math.sin(dLat/2)**2+Math.cos(a.lat*p)*Math.cos(b.lat*p)*Math.sin(dLon/2)**2;
    return 2*R*Math.asin(Math.sqrt(s));
  }
  function allKnownLakes(){return [...benchmarkLakes,...dynamicLakes.values()];}
  function isOfficial(lake){return lake?.registry==='official';}
  function isRegional(lake){return isOfficial(lake) && !lake.enriched;}
  function areaClass(km2){
    if(!Number.isFinite(km2))return 'medium';
    if(km2<2)return 'small'; if(km2<50)return 'medium'; if(km2<500)return 'large'; return 'huge';
  }
  function depthClass(m){
    if(!Number.isFinite(m)||m<=0)return 'medium';
    if(m<3)return 'shallow'; if(m<12)return 'medium'; if(m<35)return 'deep'; return 'verydeep';
  }

  // Transparent phase-1 continental climatology. Official-registry lakes use latitude-first
  // regional guidance until HydroLAKES morphology + historical calibration are attached.
  function morphologyBaselineDoy(lake){
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

  function weatherShiftDays(weather){
    if(!weather || !Number.isFinite(weather.tdd7)) return 0;
    return clamp((weather.tdd7-18)/7, -4, 5);
  }

  function evalPhysicsModel(model,features){
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

  function leadBracket(lead,minLead=7){
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

  async function refreshSeasonalPhysics(lake){
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

  function lakeModel(lake, targetDate){
    const base = baselineMedianDoy(lake);
    const currentSpring = activeSeason(today) && targetDate.getFullYear()===today.getFullYear();
    const physics = currentSpring ? seasonalPhysicsCorrection(lake) : null;
    const seasonalPhysicsApplied = Number.isFinite(physics?.correction);
    const forecastFallbackApplied = currentSpring && !seasonalPhysicsApplied && state.weather && state.weather.lakeId===lake.id;
    const forecastShift = forecastFallbackApplied ? weatherShiftDays(state.weather) : 0;
    // correctionDays is positive when breakup is shifted later. The short-range fallback is positive earlier.
    const correctionDays = seasonalPhysicsApplied ? physics.correction : -forecastShift;
    const median = Math.round(base + correctionDays);
    let spread = lake.area==='huge' || lake.depth==='verydeep' ? 15 : lake.depth==='deep' ? 12 : 10;
    if(isRegional(lake)) spread = lake.lat>60 ? 22 : 18;
    else if(isOfficial(lake) && lake.enriched) spread = Math.max(spread,13);
    const targetDoy = doy(targetDate);
    const probParam=seasonalPhysicsApplied?seasonalProbabilityParameter(lake,physics):null;
    const scale = probParam?.scale ?? (lake.history?.type==='regional' ? 6.5 : Math.max(4.8, spread/2.1));
    let probability;
    if(lake.history?.type==='direct' && Array.isArray(lake.history.doys) && lake.history.doys.length>=5){
      const smooth=probParam?.smoothing ?? 3;
      probability=lake.history.doys.reduce((sum,d)=>sum+1/(1+Math.exp(-(targetDoy-correctionDays-d)/smooth)),0)/lake.history.doys.length;
    }else{probability=1/(1+Math.exp(-(targetDoy-median)/scale));}
    let p10 = Math.round(median - spread), p90 = Math.round(median + spread);
    let winLo = Math.round(median - spread*.45), winHi = Math.round(median + spread*.45);
    if(lake.history?.type==='direct'){
      const h=lake.history;
      if(Number.isFinite(h.p10Doy))p10=Math.round(h.p10Doy+correctionDays);
      if(Number.isFinite(h.p90Doy))p90=Math.round(h.p90Doy+correctionDays);
      if(Number.isFinite(h.p25Doy))winLo=Math.round(h.p25Doy+correctionDays);
      else if(Number.isFinite(h.p20Doy))winLo=Math.round(h.p20Doy+correctionDays);
      if(Number.isFinite(h.p75Doy))winHi=Math.round(h.p75Doy+correctionDays);
      else if(Number.isFinite(h.p80Doy))winHi=Math.round(h.p80Doy+correctionDays);
    }
    // Without seasonal physics, retain the validated regional climatological intervals.
    if(lake.history?.type==='regional'&&!seasonalPhysicsApplied){p10=median-14;p90=median+14;winLo=median-7;winHi=median+7;}
    if(seasonalPhysicsApplied){
      const ints=seasonalIntervalOffsets(lake,physics);
      if(ints){p10=Math.round(median+ints.p10);p90=Math.round(median+ints.p90);winLo=Math.round(median+ints.p25);winHi=Math.round(median+ints.p75);}
    }
    let confidence = lake.history?.type==='direct' && lake.history.records>=20 ? 'Moderate–high'
      : lake.history?.type==='regional' ? 'Moderate'
      : isRegional(lake) ? 'Low' : isOfficial(lake) ? 'Moderate' : 'Moderate';
    if(!isRegional(lake) && (lake.lat>60 || lake.area==='huge')) confidence='Low–moderate';
    if(state.weatherError && activeSeason(today) && !seasonalPhysicsApplied) confidence='Low';
    return {base,correctionDays,physicsCorrection:physics?.correction??null,forecastShift,median,p10,p90,winLo,winHi,probability,confidence,applyWeather:seasonalPhysicsApplied||forecastFallbackApplied,seasonalPhysicsApplied,forecastFallbackApplied,physicsLead:physics?.lead??(baselineMedianDoy(lake)-doy(today)),physicsFamily:physics?.family??null};
  }

  function statusFor(p){
    if(p<.1) return ['Likely frozen','#8be9ff'];
    if(p<.3) return ['Early chance','#3a8cff'];
    if(p<.65) return ['Transition window','#f6b95b'];
    if(p<.9) return ['Likely open','#48d597'];
    return ['Strongly likely open','#48d597'];
  }

  function reasonFor(lake,m,target){
    const targetText = longDate(target);
    if(lake.history?.type==='direct'){
      const h=lake.history;
      const hist=`${h.records} observed ice-out dates (${h.firstYear}–${h.lastYear}), median ${shortDate(fromDoy(target.getFullYear(),h.medianDoy))}`;
      if(m.seasonalPhysicsApplied){const dir=m.correctionDays>=0?'later':'earlier';return `${lake.name} is directly calibrated to NSIDC history: ${hist}. Validated season-to-date freezing/thaw physics at a ${Math.round(m.physicsLead)}-day lead shifts the current-season median ${Math.abs(m.correctionDays).toFixed(1)} days ${dir}.`;}
      if(m.forecastFallbackApplied)return `${lake.name} is directly calibrated to NSIDC history: ${hist}. Seasonal-physics features are unavailable, so the current 7-day thaw forecast is being used only as a bounded fallback adjustment.`;
      return `${lake.name} is directly calibrated to NSIDC history: ${hist}. Live weather is shown separately outside the validated seasonal-physics lead window.`;
    }
    if(lake.history?.type==='regional'){
      const h=lake.history,sign=h.correctionDays>0?'later':'earlier';
      const txt=`${h.stationCount} nearby long-record lakes shift the morphology baseline ${Math.abs(h.correctionDays).toFixed(1)} days ${sign}`;
      if(m.seasonalPhysicsApplied){const dir=m.correctionDays>=0?'later':'earlier';return `Regional NSIDC calibration is active: ${txt}. A separately validated regional seasonal-physics model at ${Math.round(m.physicsLead)} days lead shifts this year's median ${Math.abs(m.correctionDays).toFixed(1)} days ${dir}.`;}
      if(m.forecastFallbackApplied)return `Regional NSIDC calibration is active: ${txt}. Seasonal physics is unavailable, so the current 7-day thaw forecast is used only as a bounded fallback.`;
      return `Regional NSIDC calibration is active: ${txt}. No single nearby lake is being treated as this lake's own history.`;
    }
    if(isRegional(lake)){
      const registry = lake.source || 'official geographic-name registry';
      if(!activeSeason(today)) return `For ${targetText}, ${lake.name} is resolved from ${registry}. Until its HydroLAKES morphology and historical ice-out calibration are attached, the date range is deliberately broad and latitude-driven. Live weather is shown but not applied outside spring breakup season.`;
      if(m.applyWeather) return `This is a regional low-confidence estimate for an officially named lake. The current 7-day thaw signal shifts the broad climatology by ${Math.abs(m.shift).toFixed(1)} days; lake morphology and historical calibration are still pending.`;
      return `This officially named lake is available immediately, but its morphology/history enrichment is still pending. The result stays broad and low-confidence rather than inventing lake-specific precision.`;
    }
    if(isOfficial(lake) && lake.enriched){
      const morph=`${lake.areaKm2.toFixed(lake.areaKm2<10?1:0)} km², ${lake.depthM>0?`${lake.depthM.toFixed(1)} m estimated mean depth`:'depth unavailable'}, ${Math.round(lake.elev||0)} m elevation`;
      if(!activeSeason(today)) return `${lake.name} has been matched to HydroLAKES morphology (${morph}). That sharpens the regional climatology, but historical lake-specific ice-out calibration is still pending.`;
      if(m.applyWeather) return `HydroLAKES morphology (${morph}) and the current 7-day thaw trajectory are both active. Historical lake-specific ice-out calibration is still pending, so confidence remains moderate.`;
      return `HydroLAKES morphology is attached (${morph}); historical lake-specific ice-out calibration is still pending.`;
    }
    if(!activeSeason(today)) return `For ${targetText}, this beta uses ${lake.name}'s latitude, elevation, basin depth class and size to establish a transparent regional climatology. Live weather is shown below but is not applied outside the spring breakup season.`;
    if(m.applyWeather){
      const dir = m.shift>1 ? 'pulling the window earlier' : m.shift<-1 ? 'pushing the window later' : 'close to climatological pace';
      return `The current 7-day thaw signal is ${dir}. The live forecast contributes ${Math.abs(m.shift).toFixed(1)} days of adjustment, capped so short-range weather cannot overwhelm the lake baseline.`;
    }
    return `The lake baseline is active, but fresh operational weather could not be applied. Probability remains climatology-driven until the forecast feed refreshes.`;
  }

  function defaultTarget(lake){return fromDoy(nextSpringYear,baselineMedianDoy(lake));}



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
  function historyAreaAgreement(lake,h,maxRatio=2.5){
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
  async function attachHistory(lake){
    if(lake.history||lake.historyAttempted)return;
    lake.historyAttempted=true;
    try{
      const data=await getIceHistory(),rows=(data.lakes||[]).filter(h=>Number.isFinite(Number(h.lat))&&Number.isFinite(Number(h.lon)));
      const lk=nameKey(lake.name),country=lake.country==='US'?'USA':'CANADA';
      const ranked=rows.filter(h=>h.country===country).map(h=>({h,d:distanceKm(lake,{lat:Number(h.lat),lng:Number(h.lon)}),same:nameKey(h.name)===lk})).sort((a,b)=>a.d-b.d);
      const direct=chooseDirectHistory(lake,ranked);
      if(direct){
        const h=direct.h;
        lake.history={type:'direct',source:'NSIDC G01377',lakecode:h.lakecode,name:h.name,distanceKm:direct.d,matchMethod:direct.matchMethod,records:Number(h.records)||0,firstYear:h.first_year,lastYear:h.last_year,medianDoy:Number(h.median_doy),p10Doy:Number(h.p10_doy),p20Doy:Number(h.p20_doy),p25Doy:Number(h.p25_doy),p75Doy:Number(h.p75_doy),p80Doy:Number(h.p80_doy),p90Doy:Number(h.p90_doy),doys:Array.isArray(h.iceout_doys)?h.iceout_doys.map(Number).filter(Number.isFinite):[],trendDaysDecade:h.trend_days_decade};
      }else{
        // Held-out optimization: use fewer/closer analogs and favor similar elevation/depth.
        const nearby=ranked.filter(x=>x.d<=500&&Number(x.h.records)>=15).slice(0,8);
        if(nearby.length>=3){
          let num=0,den=0;
          for(const x of nearby){
            const expected=morphologyBaselineDoy(histLakeObject(x.h));
            const residual=Number(x.h.median_doy)-expected;
            const elevSim=(Number(lake.elev)>0&&Number(x.h.elevation_m)>0)?Math.exp(-Math.abs(Number(lake.elev)-Number(x.h.elevation_m))/250):1;
            const depthSim=(Number(lake.depthM)>0&&Number(x.h.mean_depth_m)>0)?Math.exp(-Math.abs(Math.log(Number(lake.depthM)/Number(x.h.mean_depth_m)))/2):1;
            const w=Math.sqrt(Number(x.h.records))*Math.exp(-x.d/140)*elevSim*depthSim;
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
        if(lake.history.type==='direct'||lake.history.type==='regional')refreshSeasonalPhysics(lake);
      }
    }catch(e){console.warn('NSIDC historical calibration unavailable',e);}
  }

  // HYDROLAKES MORPHOMETRY — derived static shards, no database server required.
  async function getHydroManifest(){
    if(hydroManifest)return hydroManifest;
    const r=await fetch(`${HYDRO_BASE}/manifest.json`,{cache:'force-cache'});
    if(!r.ok)throw new Error(`HydroLAKES manifest ${r.status}`);
    hydroManifest=await r.json(); return hydroManifest;
  }
  function hydroShardKey(lat,lon,size){
    const y=Math.floor(lat/size)*size, x=Math.floor(lon/size)*size;
    const ys=y>=0?`+${String(y).padStart(2,'0')}`:`-${String(Math.abs(y)).padStart(2,'0')}`;
    const xs=x>=0?`+${String(x).padStart(3,'0')}`:`-${String(Math.abs(x)).padStart(3,'0')}`;
    return `lat${ys}_lon${xs}`;
  }
  async function loadHydroShard(key){
    if(hydrolakesCache.has(key))return hydrolakesCache.get(key);
    const p=fetch(`${HYDRO_BASE}/${key}.json`,{cache:'force-cache'}).then(async r=>r.ok?await r.json():[]).catch(()=>[]);
    hydrolakesCache.set(key,p); return p;
  }
  function chooseHydroMatch(rows,lake){
    const c=rows.map(r=>({row:r,d:distanceKm(lake,{lat:Number(r[1]),lng:Number(r[2])})})).filter(x=>Number.isFinite(x.d)).sort((a,b)=>a.d-b.d);
    const first=c[0],second=c[1]; if(!first)return null;
    const clear=first.d<=1.5 || (first.d<=5 && (!second||second.d>first.d*1.8)) || (first.d<=10 && (!second||second.d>first.d*3));
    if(!clear)return null;
    const r=first.row;
    return {hydrolakesId:Number(r[0]),hydroDistanceKm:first.d,areaKm2:Number(r[3]),depthM:Number(r[4]),elev:Number(r[5]),shoreDev:Number(r[6]),volumeMcm:Number(r[7]),lakeType:Number(r[8])};
  }
  async function findHydroMatch(lake){
    const mf=await getHydroManifest(),size=Number(mf.shard_size_degrees)||2;
    const center=hydroShardKey(lake.lat,lake.lng,size);
    const core=await loadHydroShard(center);
    let match=chooseHydroMatch(core,lake); if(match)return match;
    const y0=Math.floor(lake.lat/size)*size,x0=Math.floor(lake.lng/size)*size,keys=[];
    for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){
      const k=hydroShardKey(y0+dy*size,x0+dx*size,size); if(k!==center)keys.push(k);
    }
    const rows=[...core,...(await Promise.all(keys.map(loadHydroShard))).flat()];
    return chooseHydroMatch(rows,lake);
  }
  async function enrichLake(lake){
    if(!isOfficial(lake)||lake.enriched||lake.enrichAttempted)return;
    lake.enrichAttempted=true; const token=++state.enrichSeq;
    try{
      const match=await findHydroMatch(lake); if(!match)return;
      Object.assign(lake,match,{enriched:true}); lake.area=areaClass(lake.areaKm2); lake.depth=depthClass(lake.depthM);
      if(state.lake.id===lake.id&&token===state.enrichSeq){
        if(!state.targetTouched)$('targetDate').value=fmtDate(defaultTarget(lake));
        ensureMarker(lake).setIcon(markerIcon(true,false)); renderModel();
      }
    }catch(e){console.warn('HydroLAKES enrichment unavailable',e);}
  }

  // MAP
  const map=L.map('map',{center:[48,-92],zoom:4,zoomControl:false,attributionControl:true,minZoom:3,maxZoom:12});
  L.control.zoom({position:'bottomright'}).addTo(map);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:19,opacity:.45,attribution:'CARTO'}).addTo(map);
  map.attributionControl.addAttribution('<a href="https://earthdata.nasa.gov/gibs" target="_blank" rel="noopener">NASA GIBS</a>');
  map.attributionControl.addAttribution('Lake names: USGS GNIS / NRCan CGNDB');
  map.attributionControl.addAttribution('Morphometry: HydroLAKES / HydroSHEDS');

  const markers=new Map();
  function markerIcon(active=false,regional=false){
    return L.divIcon({className:'',html:`<div class="lake-marker${active?' active':''}${regional?' regional':''}"></div>`,iconSize:active?[24,24]:[18,18],iconAnchor:active?[12,12]:[9,9]});
  }
  function ensureMarker(lake){
    if(markers.has(lake.id)) return markers.get(lake.id);
    const mk=L.marker([lake.lat,lake.lng],{icon:markerIcon(false,isRegional(lake)),title:`${lake.name}, ${lake.region}`}).addTo(map);
    mk.on('click',()=>selectLake(lake,true));
    markers.set(lake.id,mk);
    return mk;
  }
  benchmarkLakes.forEach(ensureMarker);

  const GIBS={
    modis:{id:'MODIS_Terra_CorrectedReflectance_TrueColor',matrix:'GoogleMapsCompatible_Level9',ext:'jpg',maxNativeZoom:9},
    viirs:{id:'VIIRS_SNPP_CorrectedReflectance_TrueColor',matrix:'GoogleMapsCompatible_Level9',ext:'jpg',maxNativeZoom:9},
    aqua:{id:'MODIS_Aqua_CorrectedReflectance_TrueColor',matrix:'GoogleMapsCompatible_Level9',ext:'jpg',maxNativeZoom:9}
  };
  let satLayer=null, ndsiLayer=null;
  function gibsUrl(id,date,matrix,ext){return `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${id}/default/${date}/${matrix}/{z}/{y}/{x}.${ext}`;}
  function updateImagery(){
    const date=$('imageryDate').value;
    const sensor=GIBS[state.sensor];
    if(satLayer) map.removeLayer(satLayer);
    satLayer=L.tileLayer(gibsUrl(sensor.id,date,sensor.matrix,sensor.ext),{tileSize:256,maxNativeZoom:sensor.maxNativeZoom,maxZoom:12,opacity:.82}).addTo(map);
    if(ndsiLayer){map.removeLayer(ndsiLayer);ndsiLayer=null;}
    if(state.ndsi){
      ndsiLayer=L.tileLayer(gibsUrl('MODIS_Terra_NDSI_Snow_Cover',date,'GoogleMapsCompatible_Level8','png'),{tileSize:256,maxNativeZoom:8,maxZoom:12,opacity:.58}).addTo(map);
      $('legend').textContent='NDSI overlay: higher snow/ice index values are rendered by NASA’s product; cloud/no-decision pixels remain a key limitation. Compare adjacent dates when clouds obscure a lake.';
    }else{
      $('legend').textContent='NASA true-color imagery. Step the date backward/forward to separate persistent lake ice from moving cloud. Automatic open-water fraction is intentionally not fabricated in this beta.';
    }
  }

  // WEATHER
  function toC(temp,unit){if(unit==='F')return (temp-32)*5/9;if(unit==='K'||temp>100)return temp-273.15;return temp;}
  function summarizeTemps(points,source){
    if(!points.length) throw new Error('No forecast temperatures');
    const start=Date.now(), end=start+7*86400000;
    const valid=points.filter(p=>p.time>=start && p.time<=end && Number.isFinite(p.c)).sort((a,b)=>a.time-b.time);
    if(!valid.length) throw new Error('No forecast values in 7-day window');
    let weighted=0,hours=0,tdd=0,warmHours=0;
    for(let i=0;i<valid.length;i++){
      const next=valid[i+1]?.time || Math.min(end,valid[i].time+3600000);
      const h=clamp((next-valid[i].time)/3600000,.25,6);
      weighted += valid[i].c*h; hours+=h; tdd += Math.max(0,valid[i].c)*h/24; if(valid[i].c>0)warmHours+=h;
    }
    return {meanC:weighted/hours,tdd7:tdd,warmHours,source,count:valid.length,updated:new Date().toISOString()};
  }

  async function fetchUS(lake){
    const headers={'Accept':'application/geo+json'};
    const p=await fetch(`https://api.weather.gov/points/${lake.lat.toFixed(4)},${lake.lng.toFixed(4)}`,{headers});
    if(!p.ok)throw new Error(`NWS point ${p.status}`);
    const pj=await p.json(); const url=pj?.properties?.forecastHourly; if(!url)throw new Error('NWS hourly forecast unavailable');
    const f=await fetch(url,{headers}); if(!f.ok)throw new Error(`NWS forecast ${f.status}`);
    const j=await f.json();
    const pts=(j?.properties?.periods||[]).map(x=>({time:new Date(x.startTime).getTime(),c:toC(Number(x.temperature),x.temperatureUnit)}));
    return summarizeTemps(pts,'NWS hourly');
  }

  function degDistance(a,b){const dx=(a[0]-b.lng)*Math.cos(b.lat*Math.PI/180),dy=a[1]-b.lat;return Math.hypot(dx,dy);}
  async function fetchCanada(lake){
    let features=[];
    for(const span of [.35,.8,1.6]){
      const bbox=[lake.lng-span,lake.lat-span,lake.lng+span,lake.lat+span].join(',');
      const url=`https://api.weather.gc.ca/collections/prognos-gdps-realtime/items?f=json&limit=500&bbox=${encodeURIComponent(bbox)}`;
      const r=await fetch(url,{headers:{'Accept':'application/geo+json'}});
      if(!r.ok) continue;
      const j=await r.json(); features=j.features||[]; if(features.length)break;
    }
    if(!features.length) throw new Error('ECCC GDPS station forecast unavailable nearby');
    const stationBest=new Map();
    for(const ft of features){
      const pr=ft.properties||{}, sid=pr.prognos_station_id||pr.ade_id||'unknown';
      const co=ft.geometry?.coordinates; if(!Array.isArray(co)||co.length<2)continue;
      const d=degDistance(co,lake); const prev=stationBest.get(sid); if(!prev||d<prev.d)stationBest.set(sid,{d});
    }
    const sid=[...stationBest.entries()].sort((a,b)=>a[1].d-b[1].d)[0]?.[0];
    if(!sid)throw new Error('No usable ECCC station');
    const pts=features.filter(ft=>(ft.properties?.prognos_station_id||ft.properties?.ade_id||'unknown')===sid).map(ft=>{
      const pr=ft.properties||{}; return {time:new Date(pr.forecast_datetime).getTime(),c:toC(Number(pr.forecast_value),String(pr.unit||'C').toUpperCase())};
    }).filter(x=>Number.isFinite(x.time)&&Number.isFinite(x.c));
    const s=summarizeTemps(pts,'ECCC GDPS PROGNOS'); s.station=sid; return s;
  }

  async function refreshWeather(){
    const lake=state.lake; const token=lake.id; state.weather=null; state.weatherError=null; renderWeather(); renderModel();
    try{
      const w=lake.country==='US'?await fetchUS(lake):await fetchCanada(lake);
      if(state.lake.id!==token)return; state.weather={...w,lakeId:lake.id}; renderWeather(); renderModel();
    }catch(e){if(state.lake.id!==token)return; state.weatherError=e.message||'Forecast unavailable'; renderWeather(); renderModel();}
  }

  function renderWeather(){
    const box=$('weatherDrivers'); const w=state.weather;
    if(!w && !state.weatherError){box.innerHTML='<div class="loading">Loading live forecast…</div>';return;}
    if(state.weatherError){box.innerHTML=`<div class="driver"><span class="dot cold"></span><div><strong>Operational forecast unavailable</strong><small>${escapeHtml(state.weatherError)}</small></div><em>not applied</em></div>`;return;}
    const thaw=w.tdd7;
    const thawClass=thaw>30?'good':thaw>12?'warm':'cold';
    const thawText=thaw>30?'strong':thaw>12?'moderate':'weak';
    const used=activeSeason(today)?(state.physics?.lakeId===state.lake.id?'forward context · seasonal physics active':'fallback model input'):'off-season only';
    box.innerHTML=`
      <div class="driver"><span class="dot ${thawClass}"></span><div><strong>${thaw.toFixed(1)} °C-days</strong><small>7-day accumulated thaw energy</small></div><em>${thawText}</em></div>
      <div class="driver"><span class="dot"></span><div><strong>${w.meanC.toFixed(1)} °C</strong><small>forecast mean temperature</small></div><em>${used}</em></div>
      <div class="driver"><span class="dot"></span><div><strong>${Math.round(w.warmHours)} h</strong><small>forecast hours above freezing</small></div><em>${w.source}</em></div>`;
  }

  // OFFICIAL LAKE REGISTRIES
  function usFeatureToLake(ft){
    const p=ft?.properties||{}, co=ft?.geometry?.coordinates||[];
    const lat=Number(co[1]), lng=Number(co[0]); if(!Number.isFinite(lat)||!Number.isFinite(lng))return null;
    const fid=String(p.gaz_id||p.OBJECTID||`${lat},${lng}`);
    return {id:`gnis-${fid}`,name:p.gaz_name||'Unnamed lake',region:p.state_alpha||p.county_name||'United States',country:'US',lat,lng,depth:'medium',area:'medium',elev:0,registry:'official',source:'USGS GNIS',sourceId:fid,featureClass:p.gaz_featureclass||'Hydrographic feature'};
  }

  function caItemToLake(item){
    const lat=Number(item.latitude??item.lat),lng=Number(item.longitude??item.lon); if(!Number.isFinite(lat)||!Number.isFinite(lng))return null;
    const province=item?.province?.description||item?.province?.term||item?.province||item.location||'Canada';
    const key=String(item.key||item.cgndb_key||`${lat},${lng}`);
    return {id:`cgndb-${key}`,name:item.name||item.geoname||'Unnamed lake',region:String(province),country:'CA',lat,lng,depth:'medium',area:'medium',elev:0,registry:'official',source:'NRCan CGNDB',sourceId:key,featureClass:'Lake'};
  }

  async function searchUSOfficial(q){
    const clean=q.replace(/'/g,"''");
    const params=new URLSearchParams({where:`gaz_name LIKE '%${clean}%'`,outFields:'gaz_id,gaz_name,gaz_featureclass,state_alpha,county_name',returnGeometry:'true',outSR:'4326',f:'geojson',resultRecordCount:'8',orderByFields:'gaz_name'});
    const r=await fetch(`${US_GNIS}?${params.toString()}`,{headers:{Accept:'application/geo+json,application/json'}});
    if(!r.ok)throw new Error(`USGS names ${r.status}`);
    const j=await r.json();
    return (j.features||[]).map(usFeatureToLake).filter(Boolean).filter(l=>/lake|reservoir|pond|flowage/i.test(l.featureClass));
  }

  async function searchCAOfficial(q){
    const params=new URLSearchParams({q,category:'O',concise:'LAKE',num:'8','sort-field':'name',expand:'items.concise,items.province',select:'items.concise.term,items.province.description'});
    const r=await fetch(`${CA_NAMES}?${params.toString()}`,{headers:{Accept:'application/json'}});
    if(!r.ok)throw new Error(`NRCan names ${r.status}`);
    const j=await r.json(); const items=Array.isArray(j)?j:(j.items||j.results||[]);
    return items.map(caItemToLake).filter(Boolean);
  }

  async function nearbyUSOfficial(lake){
    const params=new URLSearchParams({where:'1=1',geometry:`${lake.lng},${lake.lat}`,geometryType:'esriGeometryPoint',inSR:'4326',spatialRel:'esriSpatialRelIntersects',distance:'100',units:'esriSRUnit_Kilometer',outFields:'gaz_id,gaz_name,gaz_featureclass,state_alpha,county_name',returnGeometry:'true',outSR:'4326',f:'geojson',resultRecordCount:'12'});
    const r=await fetch(`${US_GNIS}?${params.toString()}`,{headers:{Accept:'application/geo+json,application/json'}}); if(!r.ok)throw new Error('USGS nearby unavailable');
    const j=await r.json(); return (j.features||[]).map(usFeatureToLake).filter(Boolean).filter(l=>/lake|reservoir|pond|flowage/i.test(l.featureClass));
  }

  async function nearbyCAOfficial(lake){
    const params=new URLSearchParams({lat:String(lake.lat),lon:String(lake.lng),radius:'100',category:'O',concise:'LAKE',num:'12','sort-field':'distance',expand:'items.concise,items.province',select:'items.concise.term,items.province.description'});
    const r=await fetch(`${CA_NAMES}?${params.toString()}`,{headers:{Accept:'application/json'}}); if(!r.ok)throw new Error('NRCan nearby unavailable');
    const j=await r.json(); const items=Array.isArray(j)?j:(j.items||j.results||[]); return items.map(caItemToLake).filter(Boolean);
  }

  function rememberLake(lake){if(isOfficial(lake))dynamicLakes.set(lake.id,lake);return lake;}

  function renderModel(){
    const lake=state.lake; const target=new Date($('targetDate').value+'T12:00:00'); if(Number.isNaN(target.getTime()))return;
    const m=lakeModel(lake,target); const p=Math.round(m.probability*100); const st=statusFor(m.probability);
    const historyTag=lake.history?.type==='direct'?` · ${lake.history.records} historical ice-out dates`:lake.history?.type==='regional'?` · ${lake.history.stationCount}-lake regional history calibration`:'';
    const meta=(isOfficial(lake)&&lake.enriched
      ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · HydroLAKES ${lake.areaKm2.toFixed(lake.areaKm2<10?1:0)} km² · ${lake.depthM>0?`${lake.depthM.toFixed(1)} m avg depth`:'depth unavailable'}`
      : isRegional(lake)
        ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · official lake name · regional model`
        : `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · ${lake.depth} basin · ${lake.area} lake`)+historyTag;
    $('lakeName').textContent=lake.name; $('lakeMeta').textContent=meta;
    $('prob').textContent=`${p}%`; $('probBar').style.width=`${p}%`; $('statusChip').textContent=st[0]; $('statusChip').style.color=st[1];
    $('window').textContent=`Most likely window: ${shortDate(fromDoy(target.getFullYear(),m.winLo))}–${shortDate(fromDoy(target.getFullYear(),m.winHi))}`;
    $('median').textContent=shortDate(fromDoy(target.getFullYear(),m.median));
    $('range').textContent=`${shortDate(fromDoy(target.getFullYear(),m.p10))}–${shortDate(fromDoy(target.getFullYear(),m.p90))}`;
    $('confidence').textContent=m.confidence; $('reason').textContent=reasonFor(lake,m,target);
    $('modeNote').textContent = activeSeason(today) && target.getFullYear()===today.getFullYear()
      ? (m.seasonalPhysicsApplied?'Live spring mode: validated season-to-date freezing/thaw physics is adjusting the historical baseline.':m.forecastFallbackApplied?'Live spring mode: seasonal physics is unavailable, so the short-range thaw forecast is a bounded fallback.':'Spring mode: waiting for a validated seasonal signal; climatology is carrying the result.')
      : `Off-season outlook: live weather is visible but not applied to the ${target.getFullYear()} spring estimate.`;
    renderNearby(target);
  }

  async function renderNearby(target){
    const token=++state.nearbySeq, lake=state.lake;
    const local=allKnownLakes().filter(x=>x.id!==lake.id).map(x=>({lake:x,d:distanceKm(lake,x)})).filter(x=>x.d<300).sort((a,b)=>a.d-b.d);
    $('nearby').innerHTML=local.length?nearMarkup(local.slice(0,4),target):'<div class="loading">Finding nearby official lakes…</div>';
    bindNearby();
    try{
      const remote=lake.country==='US'?await nearbyUSOfficial(lake):await nearbyCAOfficial(lake);
      if(token!==state.nearbySeq||state.lake.id!==lake.id)return;
      const merged=new Map();
      [...local,...remote.filter(x=>x.id!==lake.id).map(x=>({lake:rememberLake(x),d:distanceKm(lake,x)}))].forEach(x=>{const prev=merged.get(x.lake.id);if(!prev||x.d<prev.d)merged.set(x.lake.id,x);});
      const arr=[...merged.values()].filter(x=>x.d>0.05&&x.d<160).sort((a,b)=>a.d-b.d).slice(0,5);
      $('nearby').innerHTML=arr.length?nearMarkup(arr,target):'<div class="sub">No official nearby lake results.</div>'; bindNearby();
    }catch(e){
      if(token!==state.nearbySeq)return;
      if(!local.length)$('nearby').innerHTML='<div class="sub">Nearby registry search unavailable; selected lake still works.</div>';
    }
  }

  function nearMarkup(arr,target){return arr.map(x=>{const m=lakeModel(x.lake,target);return `<div class="nearitem" data-id="${escapeHtml(x.lake.id)}"><div><b>${escapeHtml(x.lake.name)}</b><small>${Math.round(x.d)} km · ${escapeHtml(x.lake.region)}</small></div><div class="np">${Math.round(m.probability*100)}%</div></div>`;}).join('');}
  function bindNearby(){document.querySelectorAll('.nearitem').forEach(el=>el.addEventListener('click',()=>{const l=allKnownLakes().find(x=>x.id===el.dataset.id);if(l)selectLake(l,true);}));}

  function selectLake(lake,fly=false){
    if(!lake)return; rememberLake(lake); ensureMarker(lake); state.lake=lake; state.physics=null; state.physicsError=null; state.physicsSeq++;
    markers.forEach((m,id)=>{const obj=allKnownLakes().find(x=>x.id===id);m.setIcon(markerIcon(id===lake.id,obj?isRegional(obj):false));});
    if(!state.targetTouched)$('targetDate').value=fmtDate(defaultTarget(lake));
    if(fly)map.flyTo([lake.lat,lake.lng], isOfficial(lake)?8:(lake.area==='huge'?6:7),{duration:.65});
    $('search').value=''; $('results').classList.remove('show'); renderModel(); refreshWeather(); enrichLake(lake).finally(()=>attachHistory(lake));
  }

  let searchTimer=null;
  function resultMarkup(local,remote,errors=[]){
    const rows=[];
    if(local.length){rows.push('<div class="result-head">Calibrated benchmark lakes</div>');local.forEach(l=>rows.push(`<div class="result" data-id="${escapeHtml(l.id)}"><b>${escapeHtml(l.name)}</b><span>${escapeHtml(l.region)} · calibrated beta lake</span></div>`));}
    if(remote.length){rows.push('<div class="result-head">Official lake registries</div>');remote.forEach(l=>rows.push(`<div class="result" data-id="${escapeHtml(l.id)}"><b>${escapeHtml(l.name)}</b><span>${escapeHtml(l.region)} · ${escapeHtml(l.source)} · morphology auto-match</span></div>`));}
    if(!local.length&&!remote.length)rows.push(`<div class="result"><span>${errors.length?'Official registry lookup unavailable.':'No matching official lake found.'}</span></div>`);
    return rows.join('');
  }

  async function runOfficialSearch(q,local){
    const seq=++state.searchSeq;
    $('results').innerHTML=resultMarkup(local,[])+`<div class="result loading-row"><span>Searching USGS + NRCan official lake names…</span></div>`;
    $('results').classList.add('show'); bindSearchResults();
    const settled=await Promise.allSettled([searchUSOfficial(q),searchCAOfficial(q)]);
    if(seq!==state.searchSeq||$('search').value.trim().toLowerCase()!==q.toLowerCase())return;
    const errors=settled.filter(x=>x.status==='rejected').map(x=>x.reason?.message||'lookup error');
    const remote=settled.flatMap(x=>x.status==='fulfilled'?x.value:[]).map(rememberLake);
    const dedup=new Map(); remote.forEach(l=>{if(!local.some(x=>x.id===l.id))dedup.set(l.id,l);});
    $('results').innerHTML=resultMarkup(local,[...dedup.values()].slice(0,14),errors); $('results').classList.add('show'); bindSearchResults();
  }

  function bindSearchResults(){document.querySelectorAll('.result[data-id]').forEach(el=>el.addEventListener('click',()=>{const l=allKnownLakes().find(x=>x.id===el.dataset.id);if(l)selectLake(l,true);}));}

  function updateSearch(){
    const raw=$('search').value.trim(); const q=raw.toLowerCase(); clearTimeout(searchTimer); state.searchSeq++;
    if(!q){$('results').classList.remove('show');return;}
    const local=benchmarkLakes.filter(l=>`${l.name} ${l.region} ${l.country}`.toLowerCase().includes(q)).slice(0,8);
    $('results').innerHTML=resultMarkup(local,[]); $('results').classList.add('show'); bindSearchResults();
    if(raw.length>=3) searchTimer=setTimeout(()=>runOfficialSearch(raw,local),320);
  }

  $('search').addEventListener('input',updateSearch);
  document.addEventListener('click',e=>{if(!e.target.closest('.searchwrap'))$('results').classList.remove('show');});
  $('targetDate').addEventListener('change',()=>{state.targetTouched=true;renderModel();});
  $('imageryDate').addEventListener('change',updateImagery);
  $('sensor').addEventListener('change',e=>{state.sensor=e.target.value;updateImagery();});
  $('ndsiBtn').addEventListener('click',()=>{state.ndsi=!state.ndsi;$('ndsiBtn').classList.toggle('active',state.ndsi);updateImagery();});
  $('fitBtn').addEventListener('click',()=>map.flyTo([state.lake.lat,state.lake.lng],isOfficial(state.lake)?8:(state.lake.area==='huge'?6:7),{duration:.6}));

  $('seasonPill').textContent=activeSeason(today)?'LIVE SPRING MODEL':'OFF-SEASON · SPRING OUTLOOK';
  $('seasonPill').classList.toggle('offseason',!activeSeason(today));
  const imageryDefault = activeSeason(today) ? new Date(today.getTime()-86400000) : new Date(now.getFullYear(),3,25);
  $('imageryDate').value=fmtDate(imageryDefault);
  $('targetDate').value=fmtDate(defaultTarget(state.lake));
  updateImagery(); selectLake(state.lake,false); map.setView([state.lake.lat,state.lake.lng],6);
})();