const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync(require('path').join(__dirname,'index.html'),'utf8');
const code=html.match(/<script>([\s\S]*?)<\/script>/)[1];
function setup(seedName,seedStorage={},search="?room=ABCDEFG",audioTest=false,orbitTest=false){
  const soundEvents=[],listeners={},frames=[],timers=[];
  class AudioMock{constructor(){this.state="running";this.currentTime=0}createBuffer(channels,length){const data=new Float32Array(length);return {getChannelData(){return data}}}createBufferSource(){soundEvents.push("impact");return {connect(){},start(){}}}createOscillator(){soundEvents.push("tone");return {frequency:{setValueAtTime(){}},connect(){},start(){},stop(){}}}createGain(){return {gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){}}}resume(){return Promise.resolve()}}
  const values=new Map(seedName?[['13go:nickname',seedName]]:[]),elements=new Map();for(const [key,value] of Object.entries(seedStorage))values.set(key,value);
  class Element{constructor(){this.value='';this.textContent='';this.children=[];this.disabled=false;this.attrs={};this.classes=new Set();this.classList={toggle:(c,force)=>{const add=force===undefined?!this.classes.has(c):force;if(add)this.classes.add(c);else this.classes.delete(c);return add},add:(c)=>this.classes.add(c),remove:(c)=>this.classes.delete(c),contains:(c)=>this.classes.has(c)}}append(...x){this.children.push(...x)}replaceChildren(...x){this.children=x}setAttribute(k,v){this.attrs[k]=v}addEventListener(type,handler){this.events??={};this.events[type]=handler}getContext(){return new Proxy({createLinearGradient:()=>({addColorStop(){}}),createRadialGradient:()=>({addColorStop(){}})},{get:(o,k)=>k in o?o[k]:()=>{}})}getBoundingClientRect(){return {left:0,top:0,width:720,height:720}}click(){}}
  const document={addEventListener(type,callback){listeners[type]=callback},hidden:false,getElementById(id){if(!elements.has(id)){const el=new Element();if(id==='matchDialog')el.classes.add('hidden');elements.set(id,el)}return elements.get(id)},createElement(){return new Element()}};
  class WS{static OPEN=1;constructor(){WS.last=this;this.readyState=1}send(value){this.sent=JSON.parse(value);this.messages??=[];this.messages.push(this.sent)}close(){}message(x){this.onmessage({data:JSON.stringify(x)})}}
  const sandbox={document,location:{search,protocol:'http:',host:'localhost',origin:'http://localhost',pathname:'/'},localStorage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)},WebSocket:WS,URLSearchParams,URL,Blob,history:{replaceState(){}},fetch:async()=>({ok:true,json:async()=>({online:0,playing:0,waiting:0,list:[]})}),setTimeout:(callback,delay)=>{timers.push({callback,delay,active:true});return timers.length},clearTimeout(id){if(timers[id-1])timers[id-1].active=false},setInterval(){},confirm:()=>true,window:{scrollTo(){},...(audioTest?{AudioContext:AudioMock}:{}),...(orbitTest?{requestAnimationFrame(callback){frames.push(callback);return frames.length}}:{})},navigator:{audioSession:{}},console};
  vm.runInNewContext(code,sandbox);if(search||seedStorage["13go:active-room"])WS.last.onopen();return {ws:WS.last,e:id=>document.getElementById(id),values,soundEvents,listeners,frames,timers};
}
function game(id,result,solo=false){return {room:'ABCDEFG',gameId:id,solo,status:'finished',turn:'white',board:Array(169).fill(0),players:{black:{name:'Alice',connected:true},white:{name:'Bob',connected:true}},captures:{black:0,white:0},passes:0,moves:42,lastMove:null,dead:[],approvals:[],rematch:[],result:{winner:result,reason:'resign'}}}
let t=setup();t.ws.message({type:'welcome',role:'black',token:'owner'});t.ws.message({type:'state',state:game('g1','black')});t.ws.message({type:'state',state:game('g1','black')});t.ws.message({type:'state',state:game('g2','white')});t.e('navProfile').onclick();assert.equal(t.e('statGames').textContent,2);assert.equal(t.e('statWins').textContent,1);assert.equal(t.e('statLosses').textContent,1);assert.equal(t.e('statRate').textContent,'50%');assert.equal(t.e('historyRows').children.length,2);console.log('PASS profile wins/losses/rate and duplicate result protection');
t.ws.message({type:'state',state:game('solo1','black',true)});t.e('navProfile').onclick();assert.equal(t.e('statGames').textContent,2);assert.equal(t.e('practiceCount').textContent,'1 solo sessions completed');console.log('PASS solo practice tracked separately');
t=setup();t.ws.message({type:'welcome',role:'spectator'});t.ws.message({type:'state',state:game('watched','black')});t.e('navProfile').onclick();assert.equal(t.e('statGames').textContent,0);console.log('PASS watched games excluded from record');
t.e('profileNickname').value='Global Player';t.e('saveProfile').onclick();assert.equal(t.values.get('13go:nickname'),'Global Player');assert.equal(t.e('profileName').textContent,'Global Player');console.log('PASS profile display name saved');
t.values.set('13go:history','invalid json');t.e('navProfile').onclick();assert.equal(t.e('statGames').textContent,0);console.log('PASS malformed browser history handled');
assert(!/[가-힣]/.test(html));assert(!html.includes('id="create"'));console.log('PASS English UI and private-room button removed');

t=setup('\ub300\uad6d\uc790');t.e('navProfile').onclick();assert.equal(t.e('profileName').textContent,'Player');console.log('PASS legacy default name migrated to English');

// v1.1: live clock, queue cancellation, server timeout result and SGF retention.
t=setup();t.ws.message({type:'welcome',role:'black',token:'owner'});
let active=game('v11','white');active.status='playing';active.result=null;active.clock={remaining:{black:200,white:180},running:'white',serverTime:Date.now()/1000};
t.ws.message({type:'state',state:active});assert.equal(t.e('blackClock').textContent,'3:20');assert.equal(t.e('whiteClock').textContent,'3:00');assert.equal(t.values.get('13go:active-room'),'ABCDEFG');
active.status='waiting';active.clock.running=null;t.ws.message({type:'state',state:active});t.e('cancelMatch').onclick();assert.equal(t.ws.sent.type,'cancel');
t.ws.message({type:'state',state:{...active,status:'cancelled'}});assert.equal(t.values.get('13go:active-room'),'');console.log('PASS queue cancellation and active-room recovery marker');
t=setup();t.ws.message({type:'welcome',role:'black',token:'owner'});let timed=game('v11time','black');timed.sgf='(;GM[1]SZ[13]RE[B+T];B[aa])';timed.result.reason='time';t.ws.message({type:'state',state:timed});assert.equal(t.e('finalResult').children[1].textContent,'Time expired');assert.equal(JSON.parse(t.values.get('13go:history'))[0].sgf,timed.sgf);console.log('PASS v1.1 clock rendering, timeout result and SGF archive');

function playing(id='mobile',solo=false){const g=game(id,'black',solo);g.status='playing';g.turn='black';g.moves=0;g.result=null;return g}
function clickPoint(t,index){const step=52;t.e('board').events.click({clientX:48+(index%13)*step,clientY:48+Math.floor(index/13)*step})}
function ready(role='black',solo=false,seed={}){const t=setup(null,seed);t.ws.message({type:'welcome',role,token:'owner'});t.ws.message({type:'state',state:playing('mobile',solo)});return t}
t=ready();clickPoint(t,84);assert.equal(t.ws.sent.type,'join');assert.equal(t.e('placeMove').textContent,'Place G7');clickPoint(t,85);assert.equal(t.e('placeMove').textContent,'Place H7');clickPoint(t,85);assert.equal(t.ws.sent.type,'move');assert.equal(t.ws.sent.index,85);const n=t.ws.messages.length;t.e('placeMove').onclick();clickPoint(t,86);t.e('pass').onclick();assert.equal(t.ws.messages.length,n);assert.equal(t.e('pass').disabled,true);console.log('PASS preview then confirm, adjustment and duplicate-input guard');
t.ws.message({type:'error',message:'Illegal move'});assert.equal(t.e('placeMove').disabled,true);clickPoint(t,0);assert.equal(t.e('placeMove').textContent,'Place A13');t.e('clearMove').onclick();t.e('placeMove').onclick();assert.equal(t.ws.messages.length,n);console.log('PASS server rejection recovery and cleared selection never sends');
t=ready();clickPoint(t,84);let changed=playing();changed.moves=1;changed.turn='white';changed.board[0]=1;t.ws.message({type:'state',state:changed});t.e('placeMove').onclick();assert.equal(t.ws.sent.type,'join');assert.equal(t.e('placeMove').disabled,true);console.log('PASS stale selection cannot play after turn changes');
t=ready();clickPoint(t,84);t.ws.readyState=3;t.ws.onclose();t.e('placeMove').onclick();assert.equal(t.ws.sent.type,'join');console.log('PASS disconnection clears pending selection');
t=ready('spectator');clickPoint(t,84);assert.equal(t.ws.sent.type,'join');t=ready('white');clickPoint(t,84);assert.equal(t.ws.sent.type,'join');console.log('PASS spectator and opponent-turn taps cannot place stones');
t=ready('black',false,{'13go:confirm-moves':'off'});clickPoint(t,84);assert.equal(t.ws.sent.type,'join');clickPoint(t,85);assert.equal(t.ws.sent.type,'join');clickPoint(t,85);assert.equal(t.ws.sent.type,'move');assert.equal(t.ws.sent.index,85);console.log('PASS old quick-play preference cannot bypass two-tap confirmation');
t=ready('black',true,{'13go:solo-confirm':'on'});clickPoint(t,84);clickPoint(t,84);changed=playing('mobile',true);changed.board[84]=1;changed.moves=1;changed.turn='white';t.ws.message({type:'state',state:changed});clickPoint(t,85);assert.equal(t.ws.sent.index,84);clickPoint(t,85);assert.equal(t.ws.sent.index,85);console.log('PASS confirmed solo moves follow both colors');
t=ready();t.e('board').events.keydown({key:'ArrowRight',preventDefault(){}});assert.equal(t.e('placeMove').textContent,'Place H7');t.e('board').events.keydown({key:'Escape'});assert.equal(t.e('placeMove').disabled,true);console.log('PASS keyboard selection and cancel');
assert(html.indexOf('id="blackClock"')<html.indexOf('<canvas'));assert(html.indexOf('<canvas')<html.indexOf('id="placementControls"'));console.log('PASS clocks above board and confirmation below board');

// Menu-first entry and returning-room behavior.
t=setup(null,{},'');assert.equal(t.e('homePage').classList.contains('hidden'),false);assert.equal(t.e('playPage').classList.contains('hidden'),true);assert.equal(t.e('gameBoard').classList.contains('hidden'),true);
t.e('homePlay').onclick();assert.equal(t.e('homePage').classList.contains('hidden'),true);assert.equal(t.e('playPage').classList.contains('setup-only'),true);assert.equal(t.e('gameBoard').classList.contains('hidden'),true);
t.e('homeButton').onclick();t.e('homeWatch').onclick();assert.equal(t.e('watchPage').classList.contains('hidden'),false);assert.equal(t.e('playPage').classList.contains('hidden'),true);
t.e('homeProfile').onclick();assert.equal(t.e('profilePage').classList.contains('hidden'),false);console.log('PASS fresh entry shows menu and Play, Watch, My Page routes');
t=ready();assert.equal(t.e('homePage').classList.contains('hidden'),true);assert.equal(t.e('gameBoard').classList.contains('hidden'),false);assert.equal(t.e('playPage').classList.contains('game-only'),true);
t.e('homeButton').onclick();assert.equal(t.e('resumeGame').classList.contains('hidden'),false);t.e('resumeGame').onclick();assert.equal(t.e('playPage').classList.contains('hidden'),false);assert.equal(t.ws.sent.type,'join');console.log('PASS room links and return button preserve connected game');
let waiting=playing();waiting.status='waiting';t.ws.message({type:'state',state:waiting});assert.equal(t.e('gameBoard').classList.contains('hidden'),true);assert.equal(t.e('queueStatus').classList.contains('hidden'),false);assert.equal(t.e('startActions').classList.contains('hidden'),true);
t.ws.message({type:'state',state:playing()});assert.equal(t.e('gameBoard').classList.contains('hidden'),false);t.e('cancelMatch').onclick();assert.equal(t.ws.sent.type,'join');console.log('PASS waiting hides board; matched state opens board and prevents stale cancel');
t=setup(null,{'13go:active-room':'ABCDEFG'},'');assert.equal(t.e('playPage').classList.contains('hidden'),false);assert.equal(t.e('homePage').classList.contains('hidden'),true);console.log('PASS saved active room skips home');

t=ready('black',true);assert.equal(t.e('confirmMoves').checked,true);let soloBoard=Array(169).fill(0);
for(let move=0;move<8;move++){const before=t.ws.messages.length;clickPoint(t,move);assert.equal(t.ws.messages.length,before);clickPoint(t,move);assert.equal(t.ws.messages.length,before+1);assert.equal(t.ws.sent.type,'move');assert.equal(t.ws.sent.index,move);soloBoard[move]=move%2===0?1:-1;const g=playing('mobile',true);g.board=[...soloBoard];g.moves=move+1;g.turn=move%2===0?'white':'black';t.ws.message({type:'state',state:g});assert.equal(t.e('status').textContent,g.turn==='white'?'White to play':'Black to play');}
assert.deepEqual(soloBoard.slice(0,8),[1,-1,1,-1,1,-1,1,-1]);console.log('PASS solo two-tap placement sends eight alternating turns');
// A server rejection, invalid point or changed turn must require a new selection.
t=ready();clickPoint(t,84);clickPoint(t,84);const sent=t.ws.messages.length;t.ws.message({type:'error',message:'Illegal move'});clickPoint(t,84);assert.equal(t.ws.messages.length,sent);clickPoint(t,84);assert.equal(t.ws.messages.length,sent+1);console.log('PASS rejected move requires two fresh taps');
t=ready();clickPoint(t,84);clickPoint(t,85);clickPoint(t,84);assert.equal(t.ws.sent.type,'join');clickPoint(t,84);assert.equal(t.ws.sent.type,'move');assert.equal(t.ws.sent.index,84);console.log('PASS changing X back to an earlier point still requires confirmation');
t=ready();t.e('board').getBoundingClientRect=()=>({left:10,top:100,width:360,height:360});
t.e('board').events.click({clientX:10+(48+6*52+24)*.5,clientY:100+(48+6*52)*.5});assert.equal(t.ws.sent.type,'join');assert.equal(t.e('selectionHint').textContent,'');
t.e('board').events.click({clientX:10+(48+7*52)*.5,clientY:100+(48+6*52)*.5});assert.equal(t.ws.sent.type,'join');assert.equal(t.e('selectionHint').textContent,'');
t.e('board').events.click({clientX:10+(48+7*52)*.5,clientY:100+(48+6*52)*.5});assert.equal(t.ws.sent.index,85);console.log('PASS scaled phone coordinates and ambiguous-point correction require same-point confirmation');

t=ready();assert.equal(t.e('shell').classList.contains('game-view'),true);t.e('homeButton').onclick();assert.equal(t.e('shell').classList.contains('game-view'),false);t.e('resumeGame').onclick();assert.equal(t.e('shell').classList.contains('game-view'),true);t.e('navProfile').onclick();assert.equal(t.e('shell').classList.contains('game-view'),false);console.log('PASS expanded board layout applies only to the visible game');

assert(!html.includes('ctx.fillText('));assert(!html.includes('Tap to select'));assert(!html.includes('Tap again to play'));console.log('PASS board coordinates and routine tap instructions removed');

// New policy: display Japanese overtime and keep analysis outside review countdown.
t=setup();t.ws.message({type:'welcome',role:'black',token:'owner'});
let manners=game('manners-clock','white');manners.status='playing';manners.result=null;manners.turn='black';
manners.clock={policy:'byoyomi-manners-v1',remaining:{black:30,white:125},mainRemaining:{black:0,white:125},periods:{black:2,white:3},running:'black',turnElapsed:0,serverTime:Date.now()/1000};
t.ws.message({type:'state',state:manners});assert.equal(t.e('blackClock').textContent,'0:30 ×2');assert.equal(t.e('whiteClock').textContent,'2:05');
manners.clock.mainRemaining.black=200;manners.clock.remaining.black=200;manners.clock.turnElapsed=60;
t.ws.message({type:'state',state:manners});assert(t.e('clockNote').textContent.includes('Please move'));
manners.status='scoring';manners.adjudication={status:'analyzing'};manners.clock.running=null;manners.clock.reviewDeadline=null;
t.ws.message({type:'state',state:manners});assert.equal(t.e('clockNote').textContent,'Checking the score…');assert.equal(t.e('approve').disabled,true);
console.log('PASS byoyomi periods, private delay warning, and no countdown during analysis');

// Audio follows acknowledged actions, never previews, duplicate packets or passes.
t=setup(undefined,{},'?room=ABCDEFG',true);t.listeners.pointerdown();t.soundEvents.length=0;
let soundGame=game('audio','white');soundGame.status='playing';soundGame.result=null;soundGame.moves=0;
t.ws.message({type:'state',state:soundGame});assert.equal(t.soundEvents.length,0);
soundGame={...soundGame,moves:1,lastMove:84};t.ws.message({type:'state',state:soundGame});assert.equal(t.soundEvents.length,1);
t.ws.message({type:'state',state:soundGame});assert.equal(t.soundEvents.length,1);
soundGame={...soundGame,moves:2,lastMove:null};t.ws.message({type:'state',state:soundGame});assert.equal(t.soundEvents.length,1);
soundGame={...soundGame,moves:3,lastMove:85};t.ws.message({type:'state',state:soundGame});assert.equal(t.soundEvents.length,2);assert(!html.includes('id="soundToggle"'));
t=setup(undefined,{},'?room=ABCDEFG',true);t.listeners.pointerdown();t.soundEvents.length=0;t.ws.message({type:'welcome',role:'black',token:'owner'});
let countdownGame=game('count-audio','white');countdownGame.status='playing';countdownGame.result=null;countdownGame.turn='black';countdownGame.clock={policy:'byoyomi-manners-v1',remaining:{black:10,white:30},mainRemaining:{black:0,white:0},periods:{black:3,white:3},running:'black',serverTime:Date.now()/1000};
t.ws.message({type:'state',state:countdownGame});assert.equal(t.soundEvents.length,1);t.ws.message({type:'state',state:countdownGame});assert.equal(t.soundEvents.length,1);
countdownGame.clock.remaining.black=9;t.ws.message({type:'state',state:countdownGame});assert.equal(t.soundEvents.length,2);
countdownGame.clock.running='white';countdownGame.clock.remaining.white=8;t.ws.message({type:'state',state:countdownGame});assert.equal(t.soundEvents.length,2);
console.log('PASS acknowledged stone sounds, removed sound button, and own-turn countdown deduplication');

assert(html.includes('intro-out 2.6s'));assert(html.includes('woodenTapBuffer'));console.log('PASS wooden impact buffer and longer brand introduction');

assert(!html.includes('class="home-index"'));assert(!html.includes('<svg class="menu-arrow"'));
assert(!html.includes('Options &amp; rules'));assert(html.indexOf('Settings &amp; rules')>html.indexOf('id="profilePage"'));
t=setup();let botResult=game('preview-bot','black');botResult.testBot=true;t.ws.message({type:'welcome',role:'black',token:'owner'});t.ws.message({type:'state',state:botResult});assert.equal(t.values.get('13go:history'),undefined);
console.log('PASS plain home menus, profile settings, and test-opponent results excluded');

// First action and idle forfeits get a private audiovisual 10-second warning.
t=setup(undefined,{},'?room=ABCDEFG',true);t.listeners.pointerdown();t.soundEvents.length=0;t.ws.message({type:'welcome',role:'black',token:'owner'});
let warning=game('deadline-audio','white');warning.status='playing';warning.result=null;warning.turn='black';warning.moves=0;warning.clock={policy:'byoyomi-manners-v1',remaining:{black:280,white:300},mainRemaining:{black:280,white:300},periods:{black:3,white:3},running:'black',turnElapsed:20,serverTime:Date.now()/1000};
t.ws.message({type:'state',state:warning});assert.equal(t.e('deadlineNumber').textContent,'10');assert.equal(t.e('deadlineLabel').textContent,'First move');assert.equal(t.soundEvents.length,1);
t.ws.message({type:'state',state:warning});assert.equal(t.soundEvents.length,1);warning.clock.turnElapsed=21;t.ws.message({type:'state',state:warning});assert.equal(t.e('deadlineNumber').textContent,'9');assert.equal(t.soundEvents.length,2);
warning.moves=4;warning.clock.turnElapsed=80;t.ws.message({type:'state',state:warning});assert.equal(t.e('deadlineLabel').textContent,'Move now');assert.equal(t.e('deadlineNumber').textContent,'10');
warning.clock.running='white';t.ws.message({type:'state',state:warning});assert(t.e('deadlineCountdown').classes.has('hidden'));
warning.status='finished';warning.result={winner:'white',reason:'move_delay'};t.ws.message({type:'state',state:warning});assert(t.e('deadlineCountdown').classes.has('hidden'));assert.equal(t.e('clockNote').textContent,'');
assert(!html.includes('id="share"'));assert(!html.includes('id="downloadSgf"'));assert(!html.includes('Game complete'));
assert(html.indexOf('id="finalResult"')<html.indexOf('id="finishActions"'));
console.log('PASS pre-forfeit countdown visibility, sound deduplication, and compact result placement');

assert(html.includes('id="homeBlackStone"'));assert(html.includes('id="homeWhiteStone"'));assert(html.includes('front.parentNode.appendChild(front)'));console.log('PASS paired stones alternate foreground with reduced-motion fallback');

t=setup(undefined,{},'',false,true);const order=[];const parent={appendChild(node){order.push(node)}};t.e('homeBlackStone').parentNode=parent;t.e('homeWhiteStone').parentNode=parent;
t.frames.shift()(0);const initialBlack=t.e('homeBlackStone').attrs.transform;assert.equal(order.at(-1),t.e('homeWhiteStone'));
t.frames.shift()(7000);assert.equal(order.at(-1),t.e('homeBlackStone'));assert.notEqual(t.e('homeBlackStone').attrs.transform,initialBlack);
t.e('homePlay').onclick();t.frames.shift()(7100);assert.equal(t.frames.length,0);console.log('PASS home stones change depth order and stop animating outside home');

// Start/results appear once per game, respect spectator role, and restore board controls.
t=setup();t.ws.message({type:'welcome',role:'black',token:'owner'});let pop=game('popup-game','white');pop.status='playing';pop.result=null;pop.moves=0;pop.turn='black';pop.spectators=3;pop.clock={running:'black',remaining:{black:300,white:300}};
t.ws.message({type:'state',state:pop});assert.equal(t.e('matchDialogTitle').textContent,'Ready to play');assert(!t.e('matchDialog').classes.has('hidden'));assert.equal(t.e('spectatorNumber').textContent,'3');assert.equal(t.e('shell').inert,true);
t.timers.find(timer=>timer.delay===2200&&timer.active).callback();assert(t.e('matchDialog').classes.has('hidden'));assert.equal(t.e('shell').inert,false);t.ws.message({type:'state',state:pop});assert(t.e('matchDialog').classes.has('hidden'));
pop.status='finished';pop.result={winner:'white',reason:'resign'};t.ws.message({type:'state',state:pop});assert.equal(t.e('matchDialogTitle').textContent,'You lose');assert.equal(t.e('matchDialogDetail').textContent,'White · By resignation');t.e('matchDialogConfirm').onclick();t.ws.message({type:'state',state:pop});assert(t.e('matchDialog').classes.has('hidden'));assert(!t.e('finalResult').classes.has('hidden'));
pop={...pop,gameId:'rematch-popup',status:'playing',result:null};t.ws.message({type:'state',state:pop});assert(!t.e('matchDialog').classes.has('hidden'));
t=setup();t.ws.message({type:'welcome',role:'spectator'});t.ws.message({type:'state',state:pop});assert(t.e('matchDialog').classes.has('hidden'));assert.equal(t.e('spectatorNumber').textContent,'3');
assert(!html.includes('Rating +'));console.log('PASS start/end popup deduplication, auto-dismiss, spectator count, and no fictitious rating');

assert(html.includes("navigator.audioSession.type='playback'"));t=setup(undefined,{},'?room=ABCDEFG',true);assert.equal(typeof t.listeners.touchend,'function');assert.equal(typeof t.listeners.click,'function');assert.equal(typeof t.listeners.visibilitychange,'function');t.listeners.touchend();t.soundEvents.length=0;t.ws.message({type:'state',state:{...playing('ios-audio'),moves:0}});t.ws.message({type:'state',state:{...playing('ios-audio'),moves:1,lastMove:84}});assert.equal(t.soundEvents.length,1);console.log('PASS iOS touch-end audio activation and playback session');

const stoneWav=fs.readFileSync(require('path').join(__dirname,'stone-placement.wav'));let pcmPeak=0;const dataOffset=stoneWav.indexOf(Buffer.from('data'));assert(dataOffset>=0);for(let i=dataOffset+8;i+1<stoneWav.length;i+=2)pcmPeak=Math.max(pcmPeak,Math.abs(stoneWav.readInt16LE(i)));assert(pcmPeak>10000,'Recorded stone sound must contain an audible impact');assert(html.includes('if(peak>.001)recordedTapBuffer=buffer'));console.log('PASS recorded WAV is audible and silent decoded samples fall back');
