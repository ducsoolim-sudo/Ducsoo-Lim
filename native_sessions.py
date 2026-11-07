"""Opt-in guest transport for bundled native previews; no social/account login."""
import os
import secrets
import time
from aiohttp import web
import auth

PROFILE = 'go13.native.profile'
SESSION = 'go13.native.session'
ALLOWED = {'/api/profile', '/api/lobby', '/api/rooms', '/api/match',
           '/api/test-match', '/api/native/socket-ticket', '/api/native/revoke'}
TTL = 30 * 86400


def enabled():
    return os.getenv('GO13_PREVIEW') == 'true' and os.getenv('GO13_NATIVE_PREVIEW') == 'true'


def require_enabled():
    if not enabled():
        raise web.HTTPNotFound()


def token_value(value):
    if not isinstance(value, str) or len(value) != 43 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in value):
        raise web.HTTPUnauthorized(text='Native session unavailable')
    return value


async def session_for(store, session_hash):
    value = await store.auth_get('native-session:' + session_hash)
    if not value:
        raise web.HTTPUnauthorized(text='Native session expired')
    return value


def middleware(store_key):
    @web.middleware
    async def validate(request, handler):
        if request.path.startswith('/api/native/') or request.path == '/ws/native':
            require_enabled()
        authorization = request.headers.get('Authorization', '')
        if authorization and request.path in ALLOWED:
            require_enabled()
            if not authorization.startswith('Bearer '):
                raise web.HTTPUnauthorized()
            token = token_value(authorization[7:])
            session_hash = auth.digest(token)
            value = await session_for(request.app[store_key], session_hash)
            request[PROFILE], request[SESSION] = value['profileKey'], session_hash
        return await handler(request)
    return validate


async def consume_ticket(request, store_key):
    require_enabled()
    ticket = token_value(request.query.get('ticket'))
    store = request.app[store_key]
    async with request.app[auth.AUTH_LOCK]:
        key = 'native-ticket:' + auth.digest(ticket)
        value = await store.auth_get(key)
        if not value:
            raise web.HTTPUnauthorized(text='Socket ticket expired')
        await store.auth_put(key, {}, 0)  # Single worker: consume before upgrade.
        session = await session_for(store, value['sessionHash'])
        request[PROFILE], request[SESSION] = session['profileKey'], value['sessionHash']


def setup(app, store_key, check_rate):
    async def create(request):
        check_rate(request)
        # Native HTTP owns this bearer. Never export an existing web cookie/account.
        token = secrets.token_urlsafe(32)
        profile_key = 'native-guest:' + auth.digest(secrets.token_urlsafe(32))
        expires = time.time() + TTL
        async with request.app[auth.AUTH_LOCK]:
            await request.app[store_key].auth_put('native-session:' + auth.digest(token),
                {'profileKey': profile_key}, expires)
        return web.json_response({'token': token, 'expiresAt': expires}, headers={'Cache-Control': 'no-store'})

    async def ticket(request):
        check_rate(request)
        session_hash = request.get(SESSION)
        if not session_hash:
            raise web.HTTPUnauthorized()
        token = secrets.token_urlsafe(32)
        async with request.app[auth.AUTH_LOCK]:
            await session_for(request.app[store_key], session_hash)
            await request.app[store_key].auth_put('native-ticket:' + auth.digest(token),
                {'sessionHash': session_hash}, time.time() + 30)
        return web.json_response({'ticket': token, 'expiresIn': 30}, headers={'Cache-Control': 'no-store'})

    async def revoke(request):
        session_hash = request.get(SESSION)
        if not session_hash:
            raise web.HTTPUnauthorized()
        async with request.app[auth.AUTH_LOCK]:
            await request.app[store_key].auth_put('native-session:' + session_hash, {}, 0)
        return web.json_response({'ok': True}, headers={'Cache-Control': 'no-store'})

    app.router.add_post('/api/native/session', create)
    app.router.add_post('/api/native/socket-ticket', ticket)
    app.router.add_post('/api/native/revoke', revoke)
