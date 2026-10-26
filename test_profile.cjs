const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync(require('path').join(__dirname,'index.html'),'utf8');
const code=html.match(/<script>([\s\S]*?)<\/script>/)[1];
function setup(seedName){
  const values=new Map(seedName?[['13go:nickname',seedName]]:[]),elements=new Map();
  class Element{constructor(){this.value='';this.textContent='';this.children=[];this.disabled=false;this.attrs={};this.classList={toggle(){},add(){},remove(){}}}append(...x){this.children.push(...x)}replaceChildren(...x){this.children=x}setAttribute(k,v){this.attrs[k]=v}addEventListener(){}getContext(){return new Proxy({createLinearGradient:()=>({addColorStop(){}}),createRadialGradient:()=>({addColorStop(){}})},{get:(o,k)=>k in o?o[k]:()=>{}})}getBoundingClientRect(){return {left:0,top:0,width:720,height:720}}click(){}}
  const document={hidden:false,getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id)},createElement(){return new Element()}};
  class WS{static OPEN=1;constructor(){WS.last=this;this.readyState=1}send(value){this.sent=JSON.parse(value)}close(){}message(x){this.onmessage({data:JSON.stringify(x)})}}
  const sandbox={document,location:{search:'?room=ABCDEFG',protocol:'http:',host:'localhost',origin:'http://localhost',pathname:'/'},localStorage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)},WebSocket:WS,URLSearchParams,URL,Blob,history:{replaceState(){}},fetch:async()=>({ok:true,json:async()=>({online:0,playing:0,waiting:0,list:[]})}),setTimeout:()=>1,clearTimeout(){},setInterval(){},confirm:()=>true,window:{scrollTo(){}},navigator:{},console};
  vm.runInNewContext(code,sandbox);WS.last.onopen();return {ws:WS.last,e:id=>document.getElementById(id),values};
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
