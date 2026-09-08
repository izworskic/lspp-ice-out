(() => {
  const $ = id => document.getElementById(id);
  const watched=['lakeName','statusChip','prob','probLabel','window','median','range','confidence','modeNote','targetDate'].map($).filter(Boolean);
  const clean=v=>String(v||'').replace(/\s+/g,' ').trim();
  const target=()=>{const v=$('targetDate')?.value,d=v?new Date(`${v}T12:00:00`):null;return d&&!Number.isNaN(d.getTime())?d:null;};

  function refresh(){
    const lake=clean($('lakeName')?.textContent)||'This lake';
    const status=clean($('statusChip')?.textContent).toLowerCase();
    const label=clean($('probLabel')?.textContent).toLowerCase();
    const prob=Number.parseInt(clean($('prob')?.textContent),10);
    const windowText=clean($('window')?.textContent).replace(/^Most likely window:\s*/i,'');
    const median=clean($('median')?.textContent),range=clean($('range')?.textContent),confidence=clean($('confidence')?.textContent);
    const mode=clean($('modeNote')?.textContent).toLowerCase();
    const d=target(),dateLabel=d?d.toLocaleDateString('en-US',{month:'short',day:'numeric'}):'the selected date';
    const open=status.includes('open water')||label.includes('ice-out complete');
    let summary,hint;
    if(open){
      summary=`${lake} is in open-water season now. This year’s ice-out is complete; the next useful timing question is the coming spring breakup after winter freeze-up.`;
      hint=`Next spring: median ${median||'—'}${range?` · 80% range ${range}`:''}${confidence?` · ${confidence} confidence`:''}.`;
    }else if(status.includes('likely frozen')||status.includes('early chance')){
      summary=`${lake} is still on the frozen side of the breakup window. Ice-out by ${dateLabel} is ${Number.isFinite(prob)?`${prob}%`:'still unlikely'}.`;
      hint=`Use ${windowText||'the likely window'} and the later side of ${range||'the forecast range'} when an open lake matters more than being first.`;
    }else if(status.includes('transition')){
      summary=`${lake} is in the breakup transition. Ice-out by ${dateLabel} is ${Number.isFinite(prob)?`${prob}%`:'uncertain'}, so the live thaw signal and satellite view matter more now.`;
      hint=`Watch the next weather updates and imagery before treating a single date as firm${range?`; the current 80% range is ${range}`:''}.`;
    }else{
      summary=`${lake} is leaning open by ${dateLabel}${Number.isFinite(prob)?` at ${prob}% probability`:''}. The map and imagery can help confirm whether persistent ice remains.`;
      hint=`For a higher-confidence plan, favor the later side of ${range||windowText||'the forecast window'} rather than the median alone.`;
    }
    if(mode.includes('off-season')&&!open)hint=`This is an off-season outlook; live weather is visible but not yet adjusting the spring estimate. ${hint}`;
    if($('decisionSummary'))$('decisionSummary').textContent=summary;
    if($('planningHint'))$('planningHint').textContent=hint;
  }
  let raf=0;const schedule=()=>{cancelAnimationFrame(raf);raf=requestAnimationFrame(refresh);};
  const observer=new MutationObserver(schedule);watched.forEach(el=>observer.observe(el,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['value']}));
  $('targetDate')?.addEventListener('change',schedule);window.addEventListener('load',schedule,{once:true});schedule();
})();
