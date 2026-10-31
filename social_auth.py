"""Firebase-brokered social sign-in; provider secrets stay at the broker."""
import asyncio
import os
import secrets
import time
import logging
from pathlib import Path

from aiohttp import web

PROVIDERS = {'google': 'google.com', 'facebook': 'facebook.com',
             'twitter': 'twitter.com', 'apple': 'apple.com'}


def public_config():
    config = {key: os.getenv(env, '').strip() for key, env in (
        ('apiKey', 'FIREBASE_API_KEY'), ('authDomain', 'FIREBASE_AUTH_DOMAIN'),
        ('projectId', 'FIREBASE_PROJECT_ID'))}
    enabled = [key for key in PROVIDERS if key in
               os.getenv('FIREBASE_AUTH_PROVIDERS', '').split(',')]
    return {'config': config, 'providers': enabled} if all(config.values()) and enabled else None


async def verify_token(token, project):
    # google-auth checks Google's signature, expiration and project audience.
    from google.oauth2.id_token import verify_firebase_token
    from google.auth.transport.requests import Request
    def verify():
        transport = Request()
        def bounded_request(*args, **kwargs):
            kwargs['timeout'] = 10
            return transport(*args, **kwargs)
        try:
            return verify_firebase_token(token, bounded_request, audience=project)
        except Exception as error:
            raise ValueError('Invalid identity token') from error
    return await asyncio.wait_for(asyncio.to_thread(verify), timeout=12)


def verified_user(claims, project, enabled):
    now = time.time()
    if (not isinstance(claims, dict) or claims.get('aud') != project
            or claims.get('iss') != 'https://securetoken.google.com/' + project
            or not isinstance(claims.get('sub'), str) or not 0 < len(claims['sub']) <= 128):
        raise ValueError('Invalid identity')
    for key in ('iat', 'exp', 'auth_time'):
        if type(claims.get(key)) not in (int, float):
            raise ValueError('Invalid token time')
    if (claims['exp'] <= now or claims['iat'] > now + 30
            or claims['auth_time'] > now + 30 or now - claims['auth_time'] > 300):
        raise ValueError('Fresh sign-in required')
    firebase = claims.get('firebase') or {}
    if firebase.get('tenant'):
        raise ValueError('Tenant sign-in is not configured')
    provider_id = firebase.get('sign_in_provider')
    provider = next((name for name, ident in PROVIDERS.items() if ident == provider_id), None)
    if provider not in enabled:
        raise ValueError('Provider is not enabled')
    identities = firebase.get('identities') or {}
    subjects = identities.get(provider_id)
    if not isinstance(subjects, list) or len(subjects) != 1 or not isinstance(subjects[0], str) or not subjects[0]:
        raise ValueError('Missing provider identity')
    subject = subjects[0]
    if len(subject) > 256:
        raise ValueError('Invalid provider identity')
    # Preserve existing GIS Google IDs; new providers have separate namespaces.
    # Never resolve identity by email or by a browser-supplied provider label.
    if provider == 'google' and claims.get('email_verified') is not True:
        raise ValueError('Unverified Google account')
    return {'id': subject if provider == 'google' else provider + ':' + subject,
            'name': str(claims.get('name') or 'Player')[:64], 'provider': provider}


def setup(app, store_key):
    import auth

    async def browser_module(request):
        root = Path(__file__).resolve().parent
        path = root / 'social-login.js'
        if not path.exists():
            path = root / 'static' / 'social-login.js'
        return web.FileResponse(path)

    async def login(request):
        auth.same_origin(request)
        config = public_config()
        if config is None:
            raise web.HTTPServiceUnavailable(text='Social sign-in is not configured')
        try:
            data = await request.json()
            token, nonce = data.get('idToken'), request.cookies.get(auth.NONCE, '')
            if (not isinstance(token, str) or not 0 < len(token) <= 12000
                    or not nonce or not isinstance(data.get('nonce'), str)
                    or not secrets.compare_digest(data['nonce'], nonce)):
                raise ValueError('Invalid request')
            claims = await verify_token(token, config['config']['projectId'])
            user = verified_user(claims, config['config']['projectId'], config['providers'])
        except (ValueError, TypeError, AttributeError, asyncio.TimeoutError) as error:
            safe_reasons = {'Invalid identity token', 'Invalid identity', 'Invalid token time',
                            'Fresh sign-in required', 'Tenant sign-in is not configured',
                            'Provider is not enabled', 'Missing provider identity',
                            'Invalid provider identity', 'Unverified Google account'}
            reason = str(error) if str(error) in safe_reasons else 'Invalid sign-in request'
            logging.warning('Social sign-in rejected: %s', reason)
            raise web.HTTPUnauthorized(text='Sign-in failed. Please try again.')
        store = request.app[store_key]
        async with request.app[auth.AUTH_LOCK]:
            if await store.auth_get('nonce:' + auth.digest(nonce)) is not None:
                raise web.HTTPUnauthorized(text='Sign-in expired. Please try again.')
            await store.auth_put('nonce:' + auth.digest(nonce), {}, time.time() + 300)
            session = secrets.token_urlsafe(32)
            await store.auth_put('session:' + auth.digest(session), user, time.time() + 30 * 86400)
        response = web.json_response({'user': user}, headers={'Cache-Control': 'no-store'})
        response.set_cookie(auth.COOKIE, session, httponly=True, secure=auth.secure_request(request),
                            samesite='Lax', max_age=30 * 86400, path='/')
        response.del_cookie(auth.NONCE, path='/')
        return response

    app.router.add_post('/api/auth/social', login)
    app.router.add_get('/static/social-login.js', browser_module)
