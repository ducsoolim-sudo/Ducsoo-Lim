const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('social-login.js','utf8')
 .replace("import(base + 'firebase-app.js')",'Promise.resolve(appSdk)')
 .replace("import(base + 'firebase-auth.js')",'Promise.resolve(authSdk)');
async function run(mode){
 const buttons=[],notices=[],requests=[];let complete=0,signedOut=0,providerSeen;
 const provider=name=>class{constructor(){this.providerId=name;this.scopes=[]}addScope(scope){this.scopes.push(scope)}};
 const authSdk={getAuth:()=>({}),useDeviceLanguage(){},setPersistence:async()=>{},inMemoryPersistence:'memory',
  GoogleAuthProvider:provider('google.com'),FacebookAuthProvider:provider('facebook.com'),TwitterAuthProvider:provider('twitter.com'),OAuthProvider:class{constructor(id){this.providerId=id}},
  signInWithPopup:async(_,p)=>{providerSeen=p.providerId;if(p.providerId==='google.com')assert(p.scopes.includes('email'));if(mode==='cancel')throw{code:'auth/popup-closed-by-user'};if(mode==='blocked')throw{code:'auth/popup-blocked'};return{user:{getIdToken:async()=> 'verified-token'}}},
  signOut:async()=>{signedOut++}};
 const ctx={window:{},appSdk:{initializeApp:()=>({})},authSdk,document:{createElement:()=>({style:{}})},fetch:async(url,opts)=>{requests.push({url,opts});return{ok:mode!=='failure',json:async()=>({nonce:'fresh-nonce'})}}};
 vm.runInNewContext(source,ctx);
 const container={replaceChildren(){buttons.length=0},append:x=>buttons.push(x)};
 await ctx.window.Go13Social.mount(container,{config:{},providers:['google','facebook','twitter','apple','unknown']},async()=>complete++,x=>notices.push(x));
 assert.equal(buttons.length,4);
 for(let i=0;i<4;i++){
  await buttons[i].onclick();assert(buttons.every(x=>x.disabled===false));
  assert.equal(providerSeen,['google.com','facebook.com','twitter.com','apple.com'][i]);
 }
 assert.equal(signedOut,4);
 if(mode==='ok'){
  assert.equal(complete,4);assert.equal(notices.length,0);
  const posts=requests.filter(r=>r.url==='/api/auth/social');assert.equal(posts.length,4);
  assert.deepEqual(JSON.parse(posts[0].opts.body),{idToken:'verified-token',nonce:'fresh-nonce'});
 }else{assert.equal(complete,0);assert.equal(notices.length,mode==='cancel'?0:4)}
}
(async()=>{for(const mode of ['ok','cancel','blocked','failure'])await run(mode);console.log('PASS four providers, fresh nonce, session failure, popup cancellation/blocking, cleanup and button recovery')})().catch(e=>{console.error(e);process.exitCode=1});
