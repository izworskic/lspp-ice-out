from pathlib import Path

p = Path('north-america/app.js')
s = p.read_text()

needle = "  const activeSeason = (d=today) => d.getMonth() >= 1 && d.getMonth() <= 6;\n"
insert = needle + "  const openWaterSeason = (d=today) => d.getMonth() === 7 || d.getMonth() === 8; // Aug-Sep: spring ice-out is complete, before the next freeze-up cycle.\n  const sameDay = (a,b) => a.getFullYear()===b.getFullYear() && a.getMonth()===b.getMonth() && a.getDate()===b.getDate();\n"
if 'const openWaterSeason' not in s:
    assert needle in s
    s = s.replace(needle, insert, 1)

old = "  function defaultTarget(lake){return fromDoy(nextSpringYear,baselineMedianDoy(lake));}\n"
new = "  function defaultTarget(lake){return fromDoy(nextSpringYear,baselineMedianDoy(lake));}\n  function currentOpenWaterState(lake,target=today){\n    // Current-state override is intentionally conservative: only Aug-Sep, only for today,\n    // and only once the lake's modeled spring median is at least three weeks behind us.\n    return openWaterSeason(today) && sameDay(target,today) && doy(today) >= baselineMedianDoy(lake)+21;\n  }\n  function initialTarget(lake){return currentOpenWaterState(lake,today)?today:defaultTarget(lake);}\n"
if 'function currentOpenWaterState' not in s:
    assert old in s
    s = s.replace(old, new, 1)

s = s.replace("fmtDate(defaultTarget(lake))", "fmtDate(initialTarget(lake))")
s = s.replace("fmtDate(defaultTarget(state.lake))", "fmtDate(initialTarget(state.lake))")

start = s.index('  function renderModel(){')
end = s.index('\n  async function renderNearby(target){', start)
replacement = r'''  function renderModel(){
    const lake=state.lake; const target=new Date($('targetDate').value+'T12:00:00'); if(Number.isNaN(target.getTime()))return;
    const currentOpen=currentOpenWaterState(lake,target);
    const m=lakeModel(lake,target);
    const springTarget=defaultTarget(lake);
    const springModel=currentOpen?lakeModel(lake,springTarget):null;
    const p=currentOpen?100:Math.round(m.probability*100);
    const st=currentOpen?['Open water season','#48d597']:statusFor(m.probability);
    const historyTag=lake.history?.type==='direct'?` · ${lake.history.records} historical ice-out dates`:lake.history?.type==='regional'?` · ${lake.history.stationCount}-lake regional history calibration`:'';
    const meta=(isOfficial(lake)&&lake.enriched
      ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · HydroLAKES ${lake.areaKm2.toFixed(lake.areaKm2<10?1:0)} km² · ${lake.depthM>0?`${lake.depthM.toFixed(1)} m avg depth`:'depth unavailable'}`
      : isRegional(lake)
        ? `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · official lake name · regional model`
        : `${lake.region} · ${lake.country==='US'?'United States':'Canada'} · ${lake.depth} basin · ${lake.area} lake`)+historyTag;
    $('lakeName').textContent=lake.name; $('lakeMeta').textContent=meta;
    $('prob').textContent=`${p}%`; $('probBar').style.width=`${p}%`; $('statusChip').textContent=st[0]; $('statusChip').style.color=st[1];
    $('probLabel').textContent=currentOpen?`${today.getFullYear()} ice-out complete`:'chance of ice-out by target date';
    const metricLabels=document.querySelectorAll('.grid3 .metric span');
    if(metricLabels.length>=3){
      metricLabels[0].textContent=currentOpen?'Next spring median':'Median';
      metricLabels[1].textContent=currentOpen?'Next spring 80% range':'80% range';
      metricLabels[2].textContent=currentOpen?'Outlook confidence':'Confidence';
    }
    if(currentOpen){
      const springYear=springTarget.getFullYear();
      const springMedian=shortDate(fromDoy(springYear,springModel.median));
      const springLo=shortDate(fromDoy(springYear,springModel.p10));
      const springHi=shortDate(fromDoy(springYear,springModel.p90));
      $('window').textContent='No new seasonal ice-out cycle yet · next cycle begins after freeze-up';
      $('median').textContent=`${springMedian} ${springYear}`;
      $('range').textContent=`${springLo}–${springHi} ${springYear}`;
      $('confidence').textContent=springModel.confidence;
      const todayText=today.toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric'});
      $('reason').textContent=`As of ${todayText}, this spring's ice-out is already complete, so today's ice-out state is 100%. The next seasonal ice-out cycle does not begin until the lake freezes again. The Spring ${springYear} outlook remains available below.`;
      $('modeNote').textContent=`Today view: ${today.getFullYear()} ice-out is complete. No new seasonal ice-out cycle is active before freeze-up. Change the target date into Spring ${springYear} to see the next ice-out probability.`;
    }else{
      $('window').textContent=`Most likely window: ${shortDate(fromDoy(target.getFullYear(),m.winLo))}–${shortDate(fromDoy(target.getFullYear(),m.winHi))}`;
      $('median').textContent=shortDate(fromDoy(target.getFullYear(),m.median));
      $('range').textContent=`${shortDate(fromDoy(target.getFullYear(),m.p10))}–${shortDate(fromDoy(target.getFullYear(),m.p90))}`;
      $('confidence').textContent=m.confidence; $('reason').textContent=reasonFor(lake,m,target);
      $('modeNote').textContent = activeSeason(today) && target.getFullYear()===today.getFullYear()
        ? (m.seasonalPhysicsApplied?'Live spring mode: validated season-to-date freezing/thaw physics is adjusting the historical baseline.':m.forecastFallbackApplied?'Live spring mode: seasonal physics is unavailable, so the short-range thaw forecast is a bounded fallback.':'Spring mode: waiting for a validated seasonal signal; climatology is carrying the result.')
        : `Off-season outlook: live weather is visible but not applied to the ${target.getFullYear()} spring estimate.`;
    }
    renderNearby(target);
  }
'''
s = s[:start] + replacement + s[end:]

oldpill = "  $('seasonPill').textContent=activeSeason(today)?'LIVE SPRING MODEL':'OFF-SEASON · SPRING OUTLOOK';\n  $('seasonPill').classList.toggle('offseason',!activeSeason(today));\n"
newpill = "  $('seasonPill').textContent=activeSeason(today)?'LIVE SPRING MODEL':openWaterSeason(today)?'OPEN-WATER SEASON':'OFF-SEASON · SPRING OUTLOOK';\n  $('seasonPill').classList.toggle('offseason',!activeSeason(today));\n"
assert oldpill in s
s = s.replace(oldpill, newpill, 1)

p.write_text(s)
