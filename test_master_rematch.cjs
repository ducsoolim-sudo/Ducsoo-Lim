const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync(require('path').join(__dirname,'index.html'),'utf8');
const code=html.match(/<script>([\s\S]*?)<\/script>/)[1];
function setup(seedName,seedStorage={},search="?room=ABCDEFG",audioTest=false,orbitTest=false){
  const soundEvents=[],listeners={},frames=[],timers=[],audioInstances=[];
  class AudioMock{constructor(){this.state="running";this.currentTime=0;this.resumeCalls=0;audioInstances.push(this)}createBuffer(channels,length){const data=new Float32Array(length);return {length,getChannelData(){return data}}}createBufferSource(){return {connect(){},start(){if(this.buffer?.length!==1)soundEvents.push("impact")},stop(){}}}createOscillator(){soundEvents.push("tone");return {frequency:{setValueAtTime(){}},connect(){},start(){},stop(){}}}createGain(){return {gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){}}}resume(){this.resumeCalls++;this.state="running";return Promise.resolve()}}
  const values=new Map(seedName?[['13go:nickname',seedName]]:[]),elements=new Map();for(const [key,value] of Object.entries(seedStorage))values.set(key,value);
  class Element{constructor(){this.value='';this.textContent='';this.children=[];this.disabled=false;this.attrs={};this.classes=new Set();this.classList={toggle:(c,force)=>{const add=force===undefined?!this.classes.has(c):force;if(add)this.classes.add(c);else this.classes.delete(c);return add},add:(c)=>this.classes.add(c),remove:(c)=>this.classes.delete(c),contains:(c)=>this.classes.has(c)}}append(...x){this.children.push(...x)}replaceChildren(...x){this.children=x}setAttribute(k,v){this.attrs[k]=v}addEventListener(type,handler){this.events??={};this.events[type]=handler}getContext(){return new Proxy({createLinearGradient:()=>({addColorStop(){}}),createRadialGradient:()=>({addColorStop(){}})},{get:(o,k)=>k in o?o[k]:()=>{}})}getBoundingClientRect(){return {left:0,top:0,width:720,height:720}}click(){}}
  const document={addEventListener(type,callback){listeners[type]=callback},hidden:false,getElementById(id){if(!elements.has(id)){const el=new Element();if(id==='matchDialog')el.classes.add('hidden');elements.set(id,el)}return elements.get(id)},createElement(tag){const el=new Element();el.tagName=tag.toUpperCase();return el}};
  class WS{static OPEN=1;constructor(){WS.last=this;this.readyState=1}send(value){this.sent=JSON.parse(value);this.messages??=[];this.messages.push(this.sent)}close(){}message(x){this.onmessage({data:JSON.stringify(x)})}}
  const sandbox={document,location:{search,protocol:'http:',host:'localhost',origin:'http://localhost',pathname:'/'},localStorage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)},WebSocket:WS,URLSearchParams,URL,Blob,history:{replaceState(){}},fetch:async()=>({ok:true,json:async()=>({online:0,playing:0,waiting:0,list:[]})}),setTimeout:(callback,delay)=>{timers.push({callback,delay,active:true});return timers.length},clearTimeout(id){if(timers[id-1])timers[id-1].active=false},setInterval(){},confirm:()=>true,window:{scrollTo(){},...(audioTest?{AudioContext:AudioMock}:{}),...(orbitTest?{requestAnimationFrame(callback){frames.push(callback);return frames.length}}:{})},navigator:{audioSession:{}},console};
  vm.runInNewContext(code.replace(/\}\)\(\);\s*$/,'window.testLoadProfile=loadProfile;window.testLoadLobby=loadLobby;})();'),sandbox);if(search||seedStorage["13go:active-room"])WS.last.onopen();return {sandbox,ws:WS.last,e:id=>document.getElementById(id),values,soundEvents,listeners,frames,timers,audioInstances};
}
function game(id,result,solo=false){return {room:'ABCDEFG',sgf:'(;SZ[13];B[aa];W[bb])',gameId:id,solo,status:'finished',turn:'white',board:Array(169).fill(0),players:{black:{name:'Alice',connected:true},white:{name:'Bob',connected:true}},captures:{black:0,white:0},passes:0,moves:42,lastMove:null,dead:[],approvals:[],rematch:[],result:{winner:result,reason:'resign'}}}

(async()=>{
 for(const color of ['black','white']){
  const t=setup();t.ws.message({type:'welcome',role:color,token:'owner'});
  const state=game('end-'+color,'white');state.testBot=true;
  t.ws.message({type:'state',state});
  const other=color==='black'?'white':'black';
  assert.equal(t.e(other+'Name').textContent,'Master');
  assert.equal(t.e('matchDialogPlayers').children[other==='black'?0:1].children[1].textContent,'Master');
  assert.equal(t.e('matchDialogAgain').classes.has('hidden'),false);
  let requests=0,release;const wait=new Promise(resolve=>release=resolve);
  t.sandbox.fetch=async(url,options)=>url==='/api/profile'?{ok:true,json:async()=>({profile:{name:'Tester',rank:'1d'}})}:url==='/api/test-match'?(requests++,assert.equal(JSON.parse(options.body).color,color),await wait):{ok:true,json:async()=>({list:[],online:0,playing:0,waiting:0})};
  const first=t.e('matchDialogAgain').onclick();await Promise.resolve();await Promise.resolve();
  const second=t.e('matchDialogAgain').onclick();release({ok:true,json:async()=>({room:'NEWROOM',token:'new',testBot:true})});
  await Promise.all([first,second]);assert.equal(requests,1);assert.equal(t.e('matchDialog').classes.has('hidden'),true);
 }
 const spectator=setup();spectator.ws.message({type:'welcome',role:'spectator'});const s=game('watch','white');s.testBot=true;spectator.ws.message({type:'state',state:s});assert.equal(spectator.e('matchDialogAgain').classes.has('hidden'),true);
 const online=setup();online.ws.message({type:'welcome',role:'black'});online.ws.message({type:'state',state:game('human','white')});assert.equal(online.e('whiteName').textContent,'Bob');assert.equal(online.e('matchDialogAgain').classes.has('hidden'),true);
 console.log('PASS Master labels, same-color fresh AI games, duplicate-click guard and spectator/human controls');
})().catch(e=>{console.error(e);process.exitCode=1});

