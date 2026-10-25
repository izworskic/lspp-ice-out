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
