import os
import unittest
from unittest.mock import patch, AsyncMock
from aiohttp.test_utils import TestClient, TestServer
import server
import auth
from storage import RoomStore


class GoogleLogin(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {'GOOGLE_CLIENT_ID': 'test-client', 'PUBLIC_ORIGIN': 'https://go.example'})
        self.env.start()
        self.store = RoomStore(path=':memory:', database_url='')
        self.client = TestClient(TestServer(server.make_app(self.store)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.env.stop()

    async def login(self, claims=None):
        config = await (await self.client.get('/api/auth/config')).json()
        claims = claims or {'sub': 'account-a', 'name': 'Tester', 'email_verified': True, 'nonce': config['nonce']}
        self.client.session.cookie_jar.update_cookies({auth.NONCE: config['nonce']})
        with patch('auth.verify_google', AsyncMock(return_value=claims)):
            return await self.client.post('/api/auth/google', json={'credential': 'signed-token'}, headers={'Origin': 'https://go.example'})

    async def test_login_cookie_and_logout_revocation(self):
        response = await self.login()
        self.assertEqual(response.status, 200)
        cookie = response.cookies[auth.COOKIE]
        self.assertTrue(cookie['httponly'])
        self.assertTrue(cookie['secure'])
        token = cookie.value
        self.client.session.cookie_jar.update_cookies({auth.COOKIE: token})
        self.assertEqual((await (await self.client.get('/api/auth/me')).json())['user']['id'], 'account-a')
        response = await self.client.post('/api/auth/logout', headers={'Origin': 'https://go.example'})
        self.assertEqual(response.status, 200)
        self.assertIsNone(await self.store.auth_get('session:' + auth.digest(token)))

    async def test_invalid_nonce_and_unverified_email(self):
        for claims in ({'sub': 'x', 'email_verified': True, 'nonce': 'wrong'}, {'sub': 'x', 'email_verified': False}):
            self.assertEqual((await self.login(claims)).status, 401)

    async def test_cross_origin_rejected(self):
        response = await self.client.post('/api/auth/google', json={'credential': 'x'}, headers={'Origin': 'https://evil.example'})
        self.assertEqual(response.status, 403)

    async def test_unconfigured_hidden_and_unavailable(self):
        with patch.dict(os.environ, {'GOOGLE_CLIENT_ID': ''}):
            config = await (await self.client.get('/api/auth/config')).json()
            self.assertEqual(config['clientId'], '')
            response = await self.client.post('/api/auth/google', headers={'Origin': 'https://go.example'})
            self.assertEqual(response.status, 503)

    async def test_server_records_not_client_claims_and_survive_room_delete(self):
        room = server.Room('AUTH')
        room.claim(None, 'A'); room.claim(None, 'B')
        room.players['black']['account_id'] = 'account-a'
        room.players['white']['account_id'] = 'account-b'
        room.act('white', {'type': 'resign'})
        await self.store.save(room)
        await self.store.save(room)
        await self.store.delete(room.code)
        a = await self.store.account_history('account-a')
        b = await self.store.account_history('account-b')
        self.assertEqual(len(a), 1)
        self.assertTrue(a[0]['won']); self.assertFalse(b[0]['won'])
        self.assertEqual(await self.store.account_history('stranger'), [])
