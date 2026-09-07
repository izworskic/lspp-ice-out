(() => {
  const lakes = window.ICEOUT_LAKES || [];
  const $ = id => document.getElementById(id);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const activeSeason = (d=today) => d.getMonth() >= 1 && d.getMonth() <= 6; // Feb-Jul
  const nextSpringYear = now.getMonth() >= 7 ? now.getFullYear()+1 : now.getFullYear();
  const state = { lake: lakes.find(x=>x.id==='lake-vermilion-mn') || lakes[0], weather:null, weatherError:null, targetTouched:false, ndsi:false, sensor:'modis' };

  const depthAdj = {shallow:-4, medium:0, deep:4, verydeep:8};
  const sizeAdj = {small:-2, medium:0, large:2, huge:5};

  function clamp(v,a,b){return Math.max(a,Math.min(b,v));}
  function fmtDate(d){return d.toISOString().slice(0,10);}
  function doy(d){const y=d.getFullYear(); return Math.floor((Date.UTC(y,d.getMonth(),d.getDate())-Date.UTC(y,0,0))/86400000);}
  function fromDoy(year,n){const d=new Date(year,0,1); d.setDate(n); return d;}
  function shortDate(d){return d.toLocaleDateString('en-US',{month:'short',day:'numeric'});}
  function longDate(d){return d.toLocaleDateString('en-US',{month:'long',day:'numeric'});}
  function distanceKm(a,b){
    const R=6371, p=Math.PI/180;
    const dLat=(b.lat-a.lat)*p,dLon=(b.lng-a.lng)*p;
    const s=Math.sin(dLat/2)**2+Math.cos(a.lat*p)*Math.cos(b.lat*p)*Math.sin(dLon/2)**2;
    return 2*R*Math.asin(Math.sqrt(s));
  }

  // Phase-1 transparent continental climatology. It is intentionally not presented as a lake-specific observed historical median.
  function baselineMedianDoy(lake){
    const latTerm = 85 + (lake.lat-40)*4.2;
    const elevTerm = (lake.elev||0)/100 * 0.8;
    const dAdj = depthAdj[lake.depth] || 0;
    const sAdj = sizeAdj[lake.area] || 0;
    return clamp(Math.round(latTerm + elevTerm + dAdj + sAdj), 92, 205);
  }

  function weatherShiftDays(weather){
    if(!weather || !Number.isFinite(weather.tdd7)) return 0;
    // Interpretable short-range adjustment, capped to prevent a 7-day forecast from overwhelming climatology.
    return clamp((weather.tdd7-18)/7, -4, 5);
  }

  function lakeModel(lake, targetDate){
    const base = baselineMedianDoy(lake);
    const applyWeather = activeSeason(today) && targetDate.getFullYear()===today.getFullYear() && state.weather && state.weather.lakeId===lake.id;
    const shift = applyWeather ? weatherShiftDays(state.weather) : 0;
    const median = Math.round(base - shift);
    const spread = lake.area==='huge' || lake.depth==='verydeep' ? 15 : lake.depth==='deep' ? 12 : 10;
    const targetDoy = doy(targetDate);
    const scale = Math.max(4.8, spread/2.1);
    const probability = 1/(1+Math.exp(-(targetDoy-median)/scale));
    const p10 = Math.round(median - spread);
    const p90 = Math.round(median + spread);
    const winLo = Math.round(median - spread*.45);
    const winHi = Math.round(median + spread*.45);
    let confidence = 'Moderate';
    if(lake.lat>60 || lake.area==='huge') confidence='Low–moderate';
    if(state.weatherError && activeSeason(today)) confidence='Low';
    return {base,shift,median,p10,p90,winLo,winHi,probability,confidence,applyWeather};
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
    if(!activeSeason(today)){
      return `For ${targetText}, this beta uses ${lake.name}'s latitude, elevation, basin depth class and size to establish a transparent regional climatology. Live weather is shown below but is not applied outside the spring breakup season.`;
    }
    if(m.applyWeather){
      const dir = m.shift>1 ? 'pulling the window earlier' : m.shift<-1 ? 'pushing the window later' : 'close to climatological pace';
      return `The current 7-day thaw signal is ${dir}. The live forecast contributes ${Math.abs(m.shift).toFixed(1)} days of adjustment, capped so short-range weather cannot overwhelm the lake baseline.`;
    }
    return `The lake baseline is active, but fresh operational weather could not be applied. Probability remains climatology-driven until the forecast feed refreshes.`;
  }

  function defaultTarget(lake){
    const year = nextSpringYear;
    return fromDoy(year,baselineMedianDoy(lake));
  }

  // MAP
  const map=L.map('map',{center:[48,-92],zoom:4,zoomControl:false,attributionControl:true,minZoom:3,maxZoom:12});
  L.control.zoom({position:'bottomright'}).addTo(map);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:19,opacity:.45,attribution:'CARTO'}).addTo(map);
  map.attributionControl.addAttribution('<a href="https://earthdata.nasa.gov/gibs" target="_blank" rel="noopener">NASA GIBS</a>');

  const markers=new Map();
  function markerIcon(active=false){return L.divIcon({className:'',html:`<div class="lake-marker${active?' active':''}"></div>`,iconSize:active?[24,24]:[18,18],iconAnchor:active?[12,12]:[9,9]});}
  lakes.forEach(l=>{
    const mk=L.marker([l.lat,l.lng],{icon:markerIcon(false),title:`${l.name}, ${l.region}`}).addTo(map);
    mk.on('click',()=>selectLake(l,true)); markers.set(l.id,mk);
  });

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
    const used=activeSeason(today)?'model input':'off-season only';
    box.innerHTML=`
      <div class="driver"><span class="dot ${thawClass}"></span><div><strong>${thaw.toFixed(1)} °C-days</strong><small>7-day accumulated thaw energy</small></div><em>${thawText}</em></div>
      <div class="driver"><span class="dot"></span><div><strong>${w.meanC.toFixed(1)} °C</strong><small>forecast mean temperature</small></div><em>${used}</em></div>
      <div class="driver"><span class="dot"></span><div><strong>${Math.round(w.warmHours)} h</strong><small>forecast hours above freezing</small></div><em>${w.source}</em></div>`;
  }

  function renderModel(){
    const lake=state.lake; const target=new Date($('targetDate').value+'T12:00:00'); if(Number.isNaN(target.getTime()))return;
    const m=lakeModel(lake,target); const p=Math.round(m.probability*100); const st=statusFor(m.probability);
    $('lakeName').textContent=lake.name; $('lakeMeta').textContent=`${lake.region} · ${lake.country==='US'?'United States':'Canada'} · ${lake.depth} basin · ${lake.area} lake`;
    $('prob').textContent=`${p}%`; $('probBar').style.width=`${p}%`; $('statusChip').textContent=st[0]; $('statusChip').style.color=st[1];
    $('window').textContent=`Most likely window: ${shortDate(fromDoy(target.getFullYear(),m.winLo))}–${shortDate(fromDoy(target.getFullYear(),m.winHi))}`;
    $('median').textContent=shortDate(fromDoy(target.getFullYear(),m.median));
    $('range').textContent=`${shortDate(fromDoy(target.getFullYear(),m.p10))}–${shortDate(fromDoy(target.getFullYear(),m.p90))}`;
    $('confidence').textContent=m.confidence; $('reason').textContent=reasonFor(lake,m,target);
    $('modeNote').textContent = activeSeason(today) && target.getFullYear()===today.getFullYear()
      ? (m.applyWeather?'Live spring mode: short-range thaw forecast is adjusting the baseline.':'Spring mode: waiting for usable live forecast; climatology is carrying the result.')
      : `Off-season outlook: live weather is visible but not applied to the ${target.getFullYear()} spring estimate.`;
    renderNearby(target);
  }

  function renderNearby(target){
    const lake=state.lake;
    const arr=lakes.filter(x=>x.id!==lake.id).map(x=>({lake:x,d:distanceKm(lake,x),m:lakeModel(x,target)})).filter(x=>x.d<550).sort((a,b)=>a.d-b.d).slice(0,4);
    $('nearby').innerHTML=arr.length?arr.map(x=>`<div class="nearitem" data-id="${x.lake.id}"><div><b>${escapeHtml(x.lake.name)}</b><small>${Math.round(x.d)} km · ${escapeHtml(x.lake.region)}</small></div><div class="np">${Math.round(x.m.probability*100)}%</div></div>`).join(''):'<div class="sub">No benchmark lakes nearby yet.</div>';
    document.querySelectorAll('.nearitem').forEach(el=>el.addEventListener('click',()=>{const l=lakes.find(x=>x.id===el.dataset.id);if(l)selectLake(l,true);}));
  }

  function escapeHtml(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}

  function selectLake(lake,fly=false){
    state.lake=lake; markers.forEach((m,id)=>m.setIcon(markerIcon(id===lake.id)));
    if(!state.targetTouched)$('targetDate').value=fmtDate(defaultTarget(lake));
    if(fly)map.flyTo([lake.lat,lake.lng], lake.area==='huge'?6:7,{duration:.65});
    $('search').value=''; $('results').classList.remove('show'); renderModel(); refreshWeather();
  }

  function updateSearch(){
    const q=$('search').value.trim().toLowerCase(); if(!q){$('results').classList.remove('show');return;}
    const matches=lakes.filter(l=>`${l.name} ${l.region} ${l.country}`.toLowerCase().includes(q)).slice(0,10);
    $('results').innerHTML=matches.length?matches.map(l=>`<div class="result" data-id="${l.id}"><b>${escapeHtml(l.name)}</b><span>${escapeHtml(l.region)} · ${l.country==='US'?'United States':'Canada'}</span></div>`).join(''):'<div class="result"><span>No benchmark lake match yet.</span></div>';
    $('results').classList.add('show'); document.querySelectorAll('.result[data-id]').forEach(el=>el.addEventListener('click',()=>selectLake(lakes.find(x=>x.id===el.dataset.id),true)));
  }

  $('search').addEventListener('input',updateSearch);
  document.addEventListener('click',e=>{if(!e.target.closest('.searchwrap'))$('results').classList.remove('show');});
  $('targetDate').addEventListener('change',()=>{state.targetTouched=true;renderModel();});
  $('imageryDate').addEventListener('change',updateImagery);
  $('sensor').addEventListener('change',e=>{state.sensor=e.target.value;updateImagery();});
  $('ndsiBtn').addEventListener('click',()=>{state.ndsi=!state.ndsi;$('ndsiBtn').classList.toggle('active',state.ndsi);updateImagery();});
  $('fitBtn').addEventListener('click',()=>map.flyTo([state.lake.lat,state.lake.lng],state.lake.area==='huge'?6:7,{duration:.6}));

  $('seasonPill').textContent=activeSeason(today)?'LIVE SPRING MODEL':'OFF-SEASON · SPRING OUTLOOK';
  $('seasonPill').classList.toggle('offseason',!activeSeason(today));
  const imageryDefault = activeSeason(today) ? new Date(today.getTime()-86400000) : new Date(now.getFullYear(),3,25);
  $('imageryDate').value=fmtDate(imageryDefault);
  $('targetDate').value=fmtDate(defaultTarget(state.lake));
  updateImagery(); selectLake(state.lake,false); map.setView([state.lake.lat,state.lake.lng],6);
})();
