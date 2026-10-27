"""Google Identity Services verification and opaque, revocable app sessions."""
import asyncio
import hashlib
import os
import secrets
import time
from aiohttp import web

COOKIE = 'go13_session'
NONCE = 'go13_nonce'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def same_origin(request):
    origin = request.headers.get('Origin', '')
    expected = os.getenv('PUBLIC_ORIGIN', '').rstrip('/')
    if not expected:
        expected = f'{request.scheme}://{request.host}'
    if origin != expected:
        raise web.HTTPForbidden(text='Invalid origin')


async def identity(request, store):
    token = request.cookies.get(COOKIE, '')
    return await store.auth_get('session:' + digest(token)) if token else None


async def config(request):
    nonce = secrets.token_urlsafe(32)
    response = web.json_response({'clientId': os.getenv('GOOGLE_CLIENT_ID', ''), 'nonce': nonce}, headers={'Cache-Control': 'no-store'})
    response.set_cookie(NONCE, nonce, httponly=True, secure=request.secure or os.getenv('PUBLIC_ORIGIN', '').startswith('https:'), samesite='Strict', max_age=300, path='/')
    return response


async def verify_google(credential, client_id):
    from google.oauth2 import id_token
    from google.auth.transport.requests import Request
    return await asyncio.to_thread(id_token.verify_oauth2_token, credential, Request(), client_id)


def setup(app, store_key):
    async def login(request):
        same_origin(request)
        client_id = os.getenv('GOOGLE_CLIENT_ID', '')
        if not client_id:
            raise web.HTTPServiceUnavailable(text='Google sign-in is not configured')
        try:
            data = await request.json()
            credential = data.get('credential', '')
            if not isinstance(credential, str) or not credential or len(credential) > 12000:
                raise ValueError()
            claims = await verify_google(credential, client_id)
            nonce = request.cookies.get(NONCE, '')
            if not nonce or not secrets.compare_digest(str(claims.get('nonce', '')), nonce):
                raise ValueError()
            if not claims.get('sub') or claims.get('email_verified') is not True:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise web.HTTPUnauthorized(text='Sign-in failed. Please try again.')
        store = request.app[store_key]
        async with request.app[AUTH_LOCK]:
            if await store.auth_get('nonce:' + digest(nonce)):
                raise web.HTTPUnauthorized(text='Sign-in expired. Please try again.')
            await store.auth_put('nonce:' + digest(nonce), {}, time.time() + 300)
            user = {'id': claims['sub'], 'name': str(claims.get('name', 'Player'))[:64]}
            token = secrets.token_urlsafe(32)
            await store.auth_put('session:' + digest(token), user, time.time() + 30 * 86400)
        response = web.json_response({'user': user}, headers={'Cache-Control': 'no-store'})
        response.set_cookie(COOKIE, token, httponly=True, secure=request.secure or os.getenv('PUBLIC_ORIGIN', '').startswith('https:'), samesite='Lax', max_age=30 * 86400, path='/')
        response.del_cookie(NONCE, path='/')
        return response

    async def me(request):
        user = await identity(request, request.app[store_key])
        records = await request.app[store_key].account_history(user['id']) if user else []
        return web.json_response({'user': user, 'games': records}, headers={'Cache-Control': 'no-store'})

    async def logout(request):
        same_origin(request)
        token = request.cookies.get(COOKIE, '')
        if token:
            await request.app[store_key].auth_put('session:' + digest(token), {}, 0)
        response = web.json_response({'ok': True})
        response.del_cookie(COOKIE, path='/')
        return response

    app[AUTH_LOCK] = asyncio.Lock()
    app.router.add_get('/api/auth/config', config)
    app.router.add_post('/api/auth/google', login)
    app.router.add_get('/api/auth/me', me)
    app.router.add_post('/api/auth/logout', logout)


AUTH_LOCK = web.AppKey('auth_lock', asyncio.Lock)
