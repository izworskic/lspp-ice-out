import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const app = readFileSync(new URL('../north-america/app.js', import.meta.url), 'utf8');
// Execute the actual production startup calendar logic with a deterministic clock.
const start = app.indexOf('(() => {') + '(() => {'.length;
const end = app.indexOf('  const dynamicLakes');
assert.ok(start > 0 && end > start);
const clockSource = app.slice(start, end);

function clockFor(year, monthIndex, day) {
  const RealDate = Date;
  const iso = new RealDate(RealDate.UTC(year, monthIndex, day, 12)).toISOString();
  class FixedDate extends RealDate {
    constructor(...args) { super(...(args.length ? args : [iso])); }
    static now() { return RealDate.parse(iso); }
  }
  return vm.runInNewContext(
    '(function(){' + clockSource + '\nreturn { nextSpringYear, winterStartYear, winterLabel, winterPlanning, spring: activeSeason(today), open: openWaterSeason(today) };})()',
    { Date: FixedDate, document: { getElementById() { return null; } }, window: { ICEOUT_LAKES: [] } }
  );
}

test('Oct 31 -> Nov 1 retains the 2026–27 winter identity and Spring 2027 forecast', () => {
  for (const day of [31, 1]) {
    const m = day === 31 ? 9 : 10;
    const data = clockFor(2026, m, day);
    assert.equal(data.nextSpringYear, 2027);
    assert.equal(data.winterStartYear, 2026);
    assert.equal(data.winterLabel, '2026–27');
    assert.equal(data.winterPlanning, true);
    assert.equal(data.spring, false);
    assert.equal(data.open, false);
  }
});

test('January is still winter planning; February begins live spring physics gate', () => {
  const january = clockFor(2027, 0, 15);
  assert.equal(january.winterLabel, '2026–27');
  assert.equal(january.nextSpringYear, 2027);
  assert.equal(january.spring, false);
  assert.equal(january.winterPlanning, true);
  const february = clockFor(2027, 1, 1);
  assert.equal(february.spring, true);
  assert.equal(february.nextSpringYear, 2027);
});

test('November UI never represents historical calibration as current freeze-up', () => {
  assert.match(app, /No current lake freeze-up or ice-out observation is verified here/);
  assert.match(app, /last winter's records are historical calibration, not today's lake state/);
  assert.match(app, /WINTER \$\{winterLabel\} · NEXT SPRING OUTLOOK/);
  assert.match(app, /Off-season outlook: live weather is visible but not applied/);
  assert.match(app, /targetDate\.getFullYear\(\)===today\.getFullYear\(\)/);
});

const ux = readFileSync(new URL('../north-america/ux.js', import.meta.url), 'utf8');
function renderDecision({status='Transition window',prob='50%',mode='Winter 2026–27 planning · Spring 2027 outlook only.',label='chance of ice-out by target date',date='2027-05-07'}={}){
  const values={lakeName:'Lake Vermilion',statusChip:status,prob,probLabel:label,window:'Most likely window: May 2–May 12',median:'May 7',range:'Apr 25–May 19',confidence:'Moderate',modeNote:mode,decisionSummary:'',planningHint:''};
  const nodes=Object.fromEntries(Object.entries(values).map(([k,textContent])=>[k,{textContent}]));
  nodes.targetDate={value:date,addEventListener(){}};
  vm.runInNewContext(ux,{document:{getElementById:id=>nodes[id]},window:{addEventListener(){}},MutationObserver:class{observe(){}},cancelAnimationFrame(){},requestAnimationFrame:fn=>{fn();return 1;},Date});
  return {summary:nodes.decisionSummary.textContent,hint:nodes.planningHint.textContent};
}
test('winter forecast probability buckets never become present-day lake observations',()=>{
  for(const [status,prob] of [['Likely frozen','5%'],['Early chance','20%'],['Transition window','50%'],['Likely open','80%'],['Strongly likely open','95%']]){
    const result=renderDecision({status,prob});
    assert.ok(result.summary.includes(prob));
    assert.match(result.summary,/May 7, 2027/);
    assert.match(result.summary,/not an observation of current ice cover/);
    assert.match(result.hint,/Live weather does not adjust/);
    assert.doesNotMatch(result.summary,/is in the breakup transition|is still on the frozen side/);
  }
});
test('spring mode and other-year off-season mode preserve their distinct evidence boundaries',()=>{
  assert.match(renderDecision({mode:'Live spring mode: validated physics'}).hint,/Check current local observations/);
  assert.match(renderDecision({mode:'Off-season outlook: live weather is visible but not applied to the 2028 spring estimate.',date:'2028-05-07'}).hint,/Spring planning only/);
});
test('loading, invalid values and seasonal open-water inference do not claim an observation',()=>{
  for(const prob of ['—','NaN%','101%','-1%'])assert.match(renderDecision({prob}).summary,/not available yet/);
  assert.match(renderDecision({mode:''}).summary,/not available yet/);
  const result=renderDecision({status:'Seasonal open-water context',prob:'Not observed',label:'Seasonal inference, not a lake observation',mode:'Seasonal open-water context only.'});
  assert.match(result.summary,/current ice cover has not been verified/);
  assert.doesNotMatch(result.summary,/100%|is complete/);
  assert.match(app,/const p=currentOpen\?null:/);
});
