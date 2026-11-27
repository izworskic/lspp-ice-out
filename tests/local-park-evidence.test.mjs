import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const html=readFileSync(new URL('../index.html',import.meta.url),'utf8');
const model=html.slice(html.indexOf('const WAWA_ICEOUT_DOYS'),html.indexOf('// MAP\n'));
const cards=html.slice(html.indexOf('function updateProbs(){'),html.indexOf('// FILMSTRIP\n'));
function render(date){
 const nodes={probDateLabel:{},probCards:{}};
 const source=model+'\n'+cards+'\nupdateProbs();({dayOfYear:dayOfYear(curDate),share:springShare(curDate,5)})';
 const result=vm.runInNewContext(source,{Date,curDate:date,document:{getElementById:id=>nodes[id]}});
 return {...result,...nodes};
}
test('off-season date never presents a current ice state or model percentage',()=>{
 for(const date of [new Date(2026,10,27),new Date(2027,0,1),new Date(2027,7,15)]){
 const r=render(date);assert.equal(r.share,null);assert.match(r.probDateLabel.textContent,/Off-season: no current lake state verified/);assert.match(r.probCards.innerHTML,/Not assessed/);assert.doesNotMatch(r.probCards.innerHTML,/100%|Ice-free|Frozen solid|years open/);
 }
});
test('spring endpoints remain sample shares, not current observations',()=>{
 for(const d of [new Date(2027,1,1),new Date(2027,4,10),new Date(2027,6,31)]){
 const r=render(d);assert.ok(r.share>=0&&r.share<=1);assert.match(r.probDateLabel.textContent,/not observed ice cover/);assert.match(r.probCards.innerHTML,/modeled samples/);assert.doesNotMatch(r.probCards.innerHTML,/Ice-free|Frozen solid|years open/);
 }
});
test('date calendar preserves model month-day in leap years and during daylight saving',()=>{
 assert.equal(render(new Date(2028,4,10)).dayOfYear,render(new Date(2027,4,10)).dayOfYear);
 assert.equal(render(new Date(2028,1,29)).dayOfYear,render(new Date(2027,1,28)).dayOfYear);
});
test('provenance and image interpretation stay explicit',()=>{
 assert.match(html,/illustrative proxy samples/);assert.match(html,/not independent observations/);assert.match(html,/No pixel here independently confirms open water/);assert.doesNotMatch(html,/transparent here = confirmed open water/i);assert.match(html,/this tool does not assess ice safety/);
});
