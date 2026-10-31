/* Provider OAuth and nonce/PKCE are handled by the official Firebase SDK. */
window.Go13Social = {
  async mount(container, settings, complete, notify) {
    const base = 'https://www.gstatic.com/firebasejs/12.4.0/';
    const [{initializeApp}, sdk] = await Promise.all([
      import(base + 'firebase-app.js'), import(base + 'firebase-auth.js')
    ]);
    const app = initializeApp(settings.config, '13go-social');
    const auth = sdk.getAuth(app);
    await sdk.setPersistence(auth, sdk.inMemoryPersistence);
    sdk.useDeviceLanguage(auth);
    const factories = {
      google: () => {const provider=new sdk.GoogleAuthProvider();provider.addScope('email');return provider;},
      facebook: () => new sdk.FacebookAuthProvider(),
      twitter: () => new sdk.TwitterAuthProvider(),
      apple: () => new sdk.OAuthProvider('apple.com')
    };
    const labels = {google:'Google', facebook:'Facebook', twitter:'X (Twitter)', apple:'Apple'};
    container.replaceChildren();
    const buttons = [];
    for (const name of settings.providers) {
      if (!factories[name]) continue;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'button secondary';
      button.textContent = 'Continue with ' + labels[name];
      button.style.marginTop = '8px';
      button.onclick = async () => {
        buttons.forEach(item => item.disabled = true);
        try {
          // Called directly from the user gesture, before any network await.
          const result = await sdk.signInWithPopup(auth, factories[name]());
          const idToken = await result.user.getIdToken(true);
          const configResponse = await fetch('/api/auth/config', {cache:'no-store'});
          if (!configResponse.ok) throw new Error('config');
          const config = await configResponse.json();
          const response = await fetch('/api/auth/social', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({idToken, nonce:config.nonce})
          });
          if (!response.ok) throw Object.assign(new Error('session'),{code:'app/session-'+response.status});
          await complete();
        } catch (error) {
          // Diagnostic code only; never log tokens, credentials or provider payloads.
          if(typeof error.code==='string'&&/^(auth|app)\/[a-z0-9-]+$/.test(error.code))console.warn('13GO sign-in:',error.code);
          if (error.code === 'auth/popup-closed-by-user' || error.code === 'auth/cancelled-popup-request') return;
          notify(error.code === 'auth/account-exists-with-different-credential'
            ? 'Use your existing sign-in method. Accounts have not been merged.'
            : error.code === 'auth/popup-blocked' || error.code === 'auth/operation-not-supported-in-this-environment'
              ? 'Please open this page in Safari or Chrome and allow the sign-in window.'
              : 'Sign-in failed. Please try again.');
        } finally {
          await sdk.signOut(auth).catch(() => {});
          buttons.forEach(item => item.disabled = false);
        }
      };
      buttons.push(button);
      container.append(button);
    }
  }
};
