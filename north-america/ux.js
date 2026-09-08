(() => {
  const $ = id => document.getElementById(id);
  const els = ['lakeName','lakeMeta','statusChip','prob','probLabel','window','median','range','confidence','modeNote','targetDate']
    .map($).filter(Boolean);

  function clean(text){ return String(text || '').replace(/\s+/g,' ').trim(); }
  function yearFromText(text){
    const m=clean(text).match(/\b(20\d{2})\b/);
    return m ? Number(m[1]) : null;
  }
  function targetDate(){
    const raw=$('targetDate')?.value;
    const d=raw ? new Date(`${raw}T12:00:00`) : null;
    return d && !Number.isNaN(d.getTime()) ? d : null;
  }

  function updateNarrative(){
    const lake=clean($('lakeName')?.textContent) || 'This lake';
    const meta=clean($('lakeMeta')?.textContent);
    const status=clean($('statusChip')?.textContent).toLowerCase();
    const probLabel=clean($('probLabel')?.textContent).toLowerCase();
    const prob=Number.parseInt(clean($('prob')?.textContent),10);
    const windowText=clean($('window')?.textContent).replace(/^Most likely window:\s*/i,'');
    const median=clean($('median')?.textContent);
    const range=clean($('range')?.textContent);
    const confidence=clean($('confidence')?.textContent);
    const mode=clean($('modeNote')?.textContent);
    const currentOpen=status.includes('open water') || probLabel.includes('ice-out complete');
    const currentYear=new Date().getFullYear();
    const springYear=yearFromText(median) || yearFromText(range) || (new Date().getMonth() >= 7 ? currentYear + 1 : currentYear);
    const td=targetDate();
    const targetLabel=td ? td.toLocaleDateString('en-US',{month:'short',day:'numeric'}) : 'your target date';

    let summary,angler,planner,owner,title;
    if(currentOpen){
      title=`Spring ${springYear} outlook`;
      summary=`${lake} is in open-water season now. This year’s ice-out is complete; the useful forecast question is when the next spring breakup is likely to happen after winter freeze-up.`;
      angler=`Ice-out is no longer the limiting factor this season. For next spring, the current median is ${median || 'still developing'}${range ? ` with an 80% range of ${range}` : ''}.`;
      planner=`For a future spring trip, use the ${range || 'forecast range'} rather than the median alone. The current outlook confidence is ${confidence || 'still being assessed'}.`;
      owner=`Today’s state and next spring’s outlook are intentionally separate: there is no active ice-out cycle again until the lake freezes for winter.`;
    } else if(status.includes('likely frozen') || status.includes('early chance')){
      title='Plan around a spring date';
      summary=`${lake} is still on the frozen side of the breakup window. The model currently puts the chance of ice-out by ${targetLabel} at ${Number.isFinite(prob)?`${prob}%`:'a low level'}.`;
      angler=`Treat ${windowText || 'the forecast window'} as the better trip-planning signal than a single day. Nearby lakes may offer an earlier alternative.`;
      planner=`If your date is flexible, plan toward the later side of the ${range || 'forecast range'} when certainty matters more than being first.`;
      owner=`The lake is still in its active ice season. Live thaw energy and hours above freezing below show whether breakup is accelerating or stalling.`;
    } else if(status.includes('transition')){
      title='Plan around a spring date';
      summary=`${lake} is in the transition window. Ice-out by ${targetLabel} is currently ${Number.isFinite(prob)?`${prob}%`:'uncertain'}, so short-term weather can materially change the timing.`;
      angler=`This is the period to watch closely. Compare the live thaw drivers, satellite view and nearby lakes before committing to an opening-week trip.`;
      planner=`The forecast is useful now, but the ${range || '80% range'} still matters. Favor dates after the center of the window when you need a higher chance of open water.`;
      owner=`Expect visible day-to-day change. Warm nights, sustained above-freezing hours and shoreline opening are more informative now than they were earlier in winter.`;
    } else {
      title='Plan around a spring date';
      summary=`${lake} is leaning open by ${targetLabel}${Number.isFinite(prob)?` at ${prob}% probability`:''}. Use the forecast window and confidence together before treating that as a firm date.`;
      angler=`The lake is moving into the more favorable side of the opening window. Satellite imagery can help confirm whether persistent ice remains.`;
      planner=`For higher confidence, target the later side of ${range || windowText || 'the forecast window'} rather than the median alone.`;
      owner=`Breakup is likely well underway or complete soon. Continue watching the current signal until the seasonal status changes to open water.`;
    }

    if(meta && currentOpen) summary += ` ${meta.split('·')[0].trim()} is shown from the selected official lake record.`;
    if(mode && !currentOpen && mode.toLowerCase().includes('off-season')) owner=`No live spring adjustment is being applied right now. The displayed outlook is climatology/history-driven until the active breakup season begins.`;

    if($('meaningSummary')) $('meaningSummary').textContent=summary;
    if($('anglerMeaning')) $('anglerMeaning').textContent=angler;
    if($('plannerMeaning')) $('plannerMeaning').textContent=planner;
    if($('ownerMeaning')) $('ownerMeaning').textContent=owner;
    if($('planningTitle')) $('planningTitle').textContent=title;
  }

  let raf=0;
  function schedule(){ cancelAnimationFrame(raf); raf=requestAnimationFrame(updateNarrative); }
  const observer=new MutationObserver(schedule);
  els.forEach(el=>observer.observe(el,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['value']}));
  $('targetDate')?.addEventListener('change',schedule);
  window.addEventListener('load',schedule,{once:true});
  schedule();
})();
