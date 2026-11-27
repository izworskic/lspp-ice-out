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
    const open=status.includes('open-water context')||label.includes('seasonal inference');
    const spring=mode.startsWith('live spring mode:')||mode.startsWith('spring mode:');
    const planning=mode.includes('winter ')||mode.includes('off-season')||mode.includes('outlook only');
    const valid=Number.isFinite(prob)&&prob>=0&&prob<=100&&d&&label.includes('chance of ice-out');
    let summary,hint;
    if(open){
      summary=`${lake} is past its expected spring breakup window according to the seasonal model. Its current ice cover has not been verified.`;
      hint=`Next spring: median ${median||'not available'}${range?` · 80% range ${range}`:''}${confidence?` · ${confidence} confidence`:''}.`;
    }else if(!valid||(!spring&&!planning)){
      summary=`The ice-out outlook for ${lake} is not available yet.`;
      hint='Wait for the model to load. No current lake condition is established.';
    }else{
      summary=`For ${lake}, the modeled chance of ice-out by ${dateLabel}, ${d.getFullYear()}, is ${prob}%. This is not an observation of current ice cover.`;
      if(status.includes('likely frozen')||status.includes('early chance')){
        hint=`For an open-water trip, consider the later side of ${range||windowText||'the forecast range'}.`;
      }else if(status.includes('transition')){
        hint=`The selected date is in the modeled breakup window${range?`; the 80% range is ${range}`:''}.`;
      }else{
        hint=`For a higher-confidence plan, favor the later side of ${range||windowText||'the forecast window'} rather than the median alone.`;
      }
      hint=planning?`Spring planning only. Live weather does not adjust this off-season estimate. ${hint}`:`${hint} Check current local observations and satellite imagery before traveling.`;
    }
    if($('decisionSummary'))$('decisionSummary').textContent=summary;
    if($('planningHint'))$('planningHint').textContent=hint;
  }
  let raf=0;const schedule=()=>{cancelAnimationFrame(raf);raf=requestAnimationFrame(refresh);};
  const observer=new MutationObserver(schedule);watched.forEach(el=>observer.observe(el,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['value']}));
  $('targetDate')?.addEventListener('change',schedule);window.addEventListener('load',schedule,{once:true});schedule();
})();
