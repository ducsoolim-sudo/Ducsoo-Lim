import time
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
import auth
import server as s

class ProfilePolicy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store=s.RoomStore(path=':memory:',database_url='')
        self.client=TestClient(TestServer(s.make_app(self.store)))
        await self.client.start_server()
        self.origin={'Origin':str(self.client.make_url('/')).rstrip('/')}
    async def asyncTearDown(self):await self.client.close()
    async def get(self):return (await (await self.client.get('/api/profile')).json())['profile']
    async def edit(self,**data):return await self.client.post('/api/profile',json=data,headers=self.origin)

    async def test_immutable_identity_and_thirty_day_boundary(self):
        initial=await self.get()
        self.assertEqual((await self.edit(id='forged')).status,400)
        with patch('auth.time.time',return_value=1000):
            self.assertEqual((await self.edit(name='First')).status,200)
            changed=await (await self.edit(name='Second')).json()
        self.assertEqual(changed['profile']['id'],initial['id'])
        deadline=1000+30*86400
        self.assertEqual(changed['profile']['nameChangeAt'],deadline)
        with patch('auth.time.time',return_value=deadline-1):
            self.assertEqual((await self.edit(name='Third')).status,409)
        with patch('auth.time.time',return_value=deadline):
            self.assertEqual((await self.edit(name='Third')).status,200)

    async def test_match_requires_valid_initial_rank_and_ignores_alternate_name(self):
        await self.get()
        self.assertEqual((await self.client.post('/api/match',json={})).status,400)
        for rank in ('9d','0k','19k',None,18):
            self.assertEqual((await self.edit(rank=rank)).status,400)
        self.assertEqual((await self.edit(name='Fixed',rank='5d')).status,200)
        seat=await (await self.client.post('/api/match',json={'name':'Bypass'})).json()
        self.assertEqual(s.ROOMS[seat['room']].players['black']['name'],'Fixed')
        self.assertEqual((await self.edit(name='While queued')).status,409)
        self.assertEqual((await self.edit(rank='1k')).status,409)

    async def test_rank_lock_survives_finished_game_and_name_update(self):
        await self.get();await self.edit(name='Fixed',rank='18k')
        a=await (await self.client.post('/api/match',json={})).json()
        # A separate cookie jar represents the other player.
        async with self.client.session.__class__(cookie_jar=__import__('aiohttp').CookieJar(unsafe=True)) as other:
            origin=str(self.client.make_url('/')).rstrip('/')
            await other.get(self.client.make_url('/api/profile'))
            response=await other.post(self.client.make_url('/api/profile'),json={'rank':'1d'},headers={'Origin':origin})
            self.assertEqual(response.status,200)
            b=await (await other.post(self.client.make_url('/api/match'),json={})).json()
        self.assertEqual(a['room'],b['room'])
        self.assertTrue((await self.get())['rankLocked'])
        room=s.ROOMS[a['room']];room.act('black',{'type':'resign'});await self.store.save(room)
        self.assertEqual((await self.edit(rank='5d')).status,409)
        self.assertEqual((await self.edit(name='New name')).status,200)
        p=await self.get();self.assertEqual(p['rank'],'18k');self.assertTrue(p['rankLocked'])

    async def test_practice_does_not_lock_rank_but_active_name_cannot_change(self):
        await self.get();await self.edit(rank='2k')
        seat=await (await self.client.post('/api/rooms',json={'solo':True})).json()
        self.assertFalse((await self.get())['rankLocked'])
        self.assertEqual((await self.edit(name='Playing')).status,409)
        room=s.ROOMS[seat['room']];room.act('black',{'type':'resign'});await self.store.save(room)
        self.assertEqual((await self.edit(rank='5d')).status,200)

    async def test_account_profile_stable_across_session_rotation(self):
        await self.store.auth_put('session:'+auth.digest('one'),{'id':'google-sub'},time.time()+100)
        self.client.session.cookie_jar.update_cookies({auth.COOKIE:'one'})
        first=await self.get();await self.edit(name='Account',rank='3d')
        await self.store.auth_put('session:'+auth.digest('two'),{'id':'google-sub'},time.time()+100)
        self.client.session.cookie_jar.update_cookies({auth.COOKIE:'two'})
        after=await self.get();self.assertEqual(first['id'],after['id']);self.assertEqual(after['name'],'Account')

    async def test_cross_origin_and_long_name_rejected(self):
        self.assertEqual((await self.client.post('/api/profile',json={'name':'Bad'},headers={'Origin':'https://evil.example'})).status,403)
        self.assertEqual((await self.edit(name='x'*17)).status,400)

    async def test_socket_cannot_rename_existing_seat(self):
        await self.get();await self.edit(name='Fixed',rank='18k')
        seat=await (await self.client.post('/api/match',json={})).json()
        ws=await self.client.ws_connect('/ws');await ws.send_json({'type':'join',**seat,'name':'Fake'})
        await ws.receive_json();d=await ws.receive_json()
        self.assertEqual(d['state']['players']['black']['name'],'Fixed')
        self.assertEqual(d['state']['players']['black']['rank'],'18k')
        self.assertIsNone(d['state']['players']['black']['mannerScore'])
        self.assertNotIn('profile_key',d['state']['players']['black'])
        await ws.close()

    async def test_stale_room_save_does_not_lock_profile(self):
        from storage import StaleRoom
        await self.get();await self.edit(rank='18k')
        seat=await (await self.client.post('/api/match',json={})).json()
        room=s.ROOMS[seat['room']]
        before=room.snapshot()
        room.status='playing';room.revision-=1
        with self.assertRaises(StaleRoom):await self.store.save(room)
        self.assertFalse((await self.get())['rankLocked'])
        room.restore(before);room.status='playing';await self.store.save(room)
        self.assertTrue((await self.get())['rankLocked'])

    async def test_direct_room_and_fresh_socket_cannot_skip_rank_selection(self):
        await self.get()
        self.assertEqual((await self.client.post('/api/rooms',json={})).status,400)
        room=s.Room('DIRECT');room.claim(None,'Old');s.ROOMS[room.code]=room
        await self.store.save(room)
        ws=await self.client.ws_connect('/ws')
        await ws.send_json({'type':'join','room':room.code})
        message=await ws.receive_json()
        self.assertEqual(message['type'],'error');self.assertIn('rank',message['message'])
        self.assertIsNone(room.players['white'])
        await ws.close()

class ProxyOrigin(unittest.TestCase):
    def test_render_https_origin_and_secure_cookie_without_trusting_headers(self):
        from types import SimpleNamespace
        req=SimpleNamespace(headers={'Origin':'https://example.onrender.com','X-Forwarded-Proto':'garbage'},scheme='http',host='example.onrender.com',secure=False)
        with patch.dict('os.environ',{'RENDER':'true','PUBLIC_ORIGIN':''}):
            auth.same_origin(req)
            self.assertTrue(auth.secure_request(req))
            req.headers['Origin']='https://evil.example'
            with self.assertRaises(s.web.HTTPForbidden):auth.same_origin(req)
