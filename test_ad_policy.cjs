const assert = require('node:assert/strict');
const Policy = require('./ad_policy.js');
const game = (id, extra = {}) => ({gameId:id,status:'finished',result:{reason:'score'},players:{black:{},white:{}},rematch:[],...extra});
const context = g => ({game:g,role:'black',action:'new-game',resultConfirmed:true,matching:false,recovering:false,connectedToActiveGame:false,rematchRequested:false});
const ready = () => {const p=new Policy({enabled:true});p.recordCompleted(game('a'),'black');p.recordCompleted(game('b'),'black');return p;};

let p=new Policy();p.recordCompleted(game('a'),'black');p.recordCompleted(game('b'),'black');assert.equal(p.eligible(context(game('b')),0),false);
p=new Policy({enabled:true});p.recordCompleted(game('a'),'black');assert.equal(p.eligible(context(game('a')),0),false);assert.equal(p.recordCompleted(game('a'),'black'),false);assert.equal(p.gamesSinceDisplay,1);
for(const bad of [game('solo',{solo:true}),game('bot',{testBot:true}),game('active',{status:'playing'}),game('cancelled',{status:'cancelled'}),game('no-white',{players:{black:{}}})])assert.equal(p.recordCompleted(bad,'black'),false);
assert.equal(p.recordCompleted(game('watch'),'spectator'),false);
console.log('PASS disabled default, first game, duplicate completion and ineligible game exclusions');

p=new Policy({enabled:true});
for(const reason of ['first_move_timeout','move_delay','time','review_timeout','repeated_departure','disconnect','cancelled','unknown',undefined]) {
 assert.equal(p.recordCompleted(game('abnormal-'+reason,{result:{reason}}),'black'),false);
}
assert.equal(p.gamesSinceDisplay,0);
assert.equal(p.recordCompleted(game('normal-score'),'black'),true);
assert.equal(p.recordCompleted(game('normal-resign',{result:{reason:'resign'}}),'black'),true);
console.log('PASS only scored or resigned human games count; timeout, departure and unknown results excluded');

p=ready();
for(const id of [null,undefined,'',5])assert.equal(p.recordDisplayed(id,0),false);
assert.equal(p.lastDisplayedAt,null);assert.equal(p.gamesSinceDisplay,2);
console.log('PASS callbacks without a pending valid game cannot consume the frequency cap');

p=ready();const c=context(game('b'));assert.equal(p.eligible(c,0),true);
for(const mutation of [{matching:true},{recovering:true},{connectedToActiveGame:true},{rematchRequested:true},{resultConfirmed:false},{action:'rematch'},{role:'spectator'},{game:game('b',{clock:{recovering:true}})},{game:game('b',{rematch:['black']})},{game:game('unknown')}])assert.equal(p.eligible({...c,...mutation},0),false);
assert.equal(p.eligible({game:c.game,role:'black',action:'new-game',resultConfirmed:true},0),false);
assert.equal(p.eligible(c,NaN),false);
console.log('PASS explicit result confirmation and safe transition required; active matching/recovery/rematch blocked');

assert.equal(p.begin(c,0),true);assert.equal(p.begin(c,0),false);assert.equal(p.recordDisplayed('wrong',0),false);assert.equal(p.lastDisplayedAt,null);p.cancel();assert.equal(p.eligible(c,0),true);
assert.equal(p.begin(c,0),true);assert.equal(p.recordDisplayed('b',0),true);assert.equal(p.recordDisplayed('b',0),false);assert.equal(p.gamesSinceDisplay,0);
p.recordCompleted(game('c'),'black');p.recordCompleted(game('d'),'black');const next=context(game('d'));
assert.equal(p.eligible(next,599999),false);assert.equal(p.eligible(next,600000),true);
p.begin(next,600000);p.cancel();assert.equal(p.gamesSinceDisplay,2);assert.equal(p.lastDisplayedAt,0);assert.equal(p.eligible(next,600000),true);
console.log('PASS no-fill/cancel preserves cap; actual display consumes two games and requires ten minutes');
