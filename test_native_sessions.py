import os
import unittest
from unittest.mock import patch
from aiohttp import WSServerHandshakeError, WSMsgType
from aiohttp.test_utils import TestClient, TestServer
import auth
import server
from storage import RoomStore


class NativeGuest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {'GO13_PREVIEW':'true', 'GO13_NATIVE_PREVIEW':'true'})
        self.env.start()
        server.REQUEST_TIMES.clear()
        self.store = RoomStore(path=':memory:', database_url='')
        self.client = TestClient(TestServer(server.make_app(self.store)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.env.stop()

    async def session(self):
        response = await self.client.post('/api/native/session')
        self.assertEqual(response.status,200)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        token = (await response.json())['token']
        return token, {'Authorization':'Bearer '+token}

    async def ticket(self, headers):
        response = await self.client.post('/api/native/socket-ticket',headers=headers)
        self.assertEqual(response.status,200)
        return (await response.json())['ticket']

    async def join(self, ticket, created):
        socket = await self.client.ws_connect('/ws/native?ticket='+ticket)
        await socket.send_json({'type':'join','room':created['room'],'token':created['token']})
        welcome = await socket.receive_json(timeout=2)
        self.assertEqual(welcome['type'],'welcome')
        return socket, welcome

    async def test_guest_reconnect_keeps_profile_and_real_seat(self):
        _, headers = await self.session()
        first = await (await self.client.get('/api/profile',headers=headers)).json()
        self.assertFalse(self.client.session.cookie_jar)  # No cookie dependency.
        response = await self.client.post('/api/profile',headers=headers,json={'name':'Native','rank':'3d'})
        self.assertEqual(response.status,200)
        created = await (await self.client.post('/api/rooms',headers=headers,json={'solo':True})).json()
        socket, welcome = await self.join(await self.ticket(headers),created)
        self.assertEqual(welcome['role'],'black')
        await socket.receive_json(timeout=2)  # Initial state.
        await socket.send_json({'type':'move','index':84})
        self.assertEqual((await socket.receive_json(timeout=2))['state']['moves'],1)
        await socket.close()
        second = await (await self.client.get('/api/profile',headers=headers)).json()
        self.assertEqual(first['profile']['id'],second['profile']['id'])
        socket, welcome = await self.join(await self.ticket(headers),created)
        self.assertEqual(welcome['role'],'black')
        self.assertEqual((await socket.receive_json(timeout=2))['state']['moves'],1)
        await socket.close()

    async def test_ticket_single_use_expiry_and_other_profile_cannot_claim_seat(self):
        _, headers = await self.session()
        created = await (await self.client.post('/api/rooms',headers=headers,json={'solo':True})).json()
        ticket = await self.ticket(headers)
        socket,_ = await self.join(ticket,created)
        await socket.close()
        with self.assertRaises(WSServerHandshakeError) as caught:
            await self.client.ws_connect('/ws/native?ticket='+ticket)
        self.assertEqual(caught.exception.status,401)
        expired = await self.ticket(headers)
        await self.store.auth_put('native-ticket:'+auth.digest(expired),{},0)
        with self.assertRaises(WSServerHandshakeError):
            await self.client.ws_connect('/ws/native?ticket='+expired)
        _, other = await self.session()
        socket = await self.client.ws_connect('/ws/native?ticket='+await self.ticket(other))
        await socket.send_json({'type':'join','room':created['room'],'token':created['token']})
        self.assertEqual((await socket.receive_json(timeout=2))['type'],'error')
        await socket.close()

    async def test_revocation_invalidates_tickets_and_future_moves(self):
        token, headers = await self.session()
        created = await (await self.client.post('/api/rooms',headers=headers,json={'solo':True})).json()
        socket,_ = await self.join(await self.ticket(headers),created)
        await socket.receive_json(timeout=2)
        ticket = await self.ticket(headers)
        self.assertEqual((await self.client.post('/api/native/revoke',headers=headers)).status,200)
        self.assertEqual((await self.client.get('/api/profile',headers=headers)).status,401)
        with self.assertRaises(WSServerHandshakeError):
            await self.client.ws_connect('/ws/native?ticket='+ticket)
        await socket.send_json({'type':'move','index':84})
        self.assertEqual((await socket.receive(timeout=2)).type,WSMsgType.CLOSE)
        self.assertEqual(server.ROOMS[created['room']].moves,0)
        self.assertIsNone(await self.store.auth_get('native-session:'+auth.digest(token)))

    async def test_disabled_by_default_and_bad_tokens_fail_closed(self):
        for env in ({'GO13_NATIVE_PREVIEW':''},{'GO13_PREVIEW':'false'}):
            with patch.dict(os.environ,env):
                self.assertEqual((await self.client.post('/api/native/session')).status,404)
        for token in ('x','a'*43):
            self.assertEqual((await self.client.get('/api/profile',headers={'Authorization':'Bearer '+token})).status,401)
        self.assertEqual((await self.client.post('/api/native/socket-ticket')).status,401)
        # Existing web CSRF protection must remain in place.
        self.assertEqual((await self.client.post('/api/profile',json={'name':'Forged'},headers={'Origin':'https://evil.example'})).status,403)

    async def test_native_session_never_adopts_web_account_cookie(self):
        await self.store.auth_put('session:'+auth.digest('web-token'),{'id':'existing-account'},9999999999)
        self.client.session.cookie_jar.update_cookies({auth.COOKIE:'web-token'})
        _, headers = await self.session()
        profile = (await (await self.client.get('/api/profile',headers=headers)).json())['profile']
        account = (await (await self.client.get('/api/profile')).json())['profile']
        self.assertNotEqual(profile['id'],account['id'])

    async def test_expired_session_and_concurrent_ticket_replay_are_rejected(self):
        token, headers = await self.session()
        ticket = await self.ticket(headers)
        socket = await self.client.ws_connect('/ws/native?ticket='+ticket)
        with self.assertRaises(WSServerHandshakeError):
            await self.client.ws_connect('/ws/native?ticket='+ticket)
        await socket.close()
        # Persist only digests, never raw bearer or socket ticket strings.
        records = await self.store.auth_query('SELECT key,payload FROM go13_auth')
        self.assertNotIn(token,str(records));self.assertNotIn(ticket,str(records))
        await self.store.auth_put('native-session:'+auth.digest(token),{},0)
        self.assertEqual((await self.client.get('/api/profile',headers=headers)).status,401)
