import os
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
import server as s


class PreviewBot(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env=patch.dict(os.environ,{'GO13_PREVIEW':'true'});self.env.start()
        self.client=TestClient(TestServer(s.make_app(s.RoomStore(path=':memory:',database_url=''))))
        await self.client.start_server()
    async def asyncTearDown(self):
        await self.client.close();self.env.stop()
    async def state(self,ws,predicate):
        while True:
            event=await ws.receive_json(timeout=4)
            self.assertNotEqual(event['type'],'error',event)
            if event['type']=='state' and predicate(event['state']):return event['state']
    async def test_real_socket_moves_reconnect_and_rematch(self):
        response=await self.client.post('/api/test-match',json={'name':'Human'})
        self.assertEqual(response.status,200)
        player=await response.json();ws=await self.client.ws_connect('/ws')
        await ws.send_json({'type':'join',**player})
        self.assertEqual((await ws.receive_json())['role'],'black')
        state=await self.state(ws,lambda _:True)
        self.assertFalse(state['solo']);self.assertTrue(state['testBot'])
        self.assertTrue(state['players']['white']['connected'])
        self.assertEqual(state['clock']['running'],'black')
        for expected in range(2,10,2):
            room=s.ROOMS[player['room']]
            for index,c in enumerate(room.board):
                if c:continue
                try:s.try_move(room.board,index,1,{room.ko_position} if room.ko_position else set())
                except ValueError:continue
                break
            await ws.send_json({'type':'move','index':index})
            state=await self.state(ws,lambda g:g['moves']>=expected)
            self.assertEqual(state['moves'],expected);self.assertEqual(state['turn'],'black')
        await ws.close();ws=await self.client.ws_connect('/ws')
        await ws.send_json({'type':'join',**player});await ws.receive_json()
        state=await self.state(ws,lambda _:True);self.assertEqual(state['moves'],8)
        await ws.send_json({'type':'resign'})
        state=await self.state(ws,lambda g:g['status']=='finished');old=state['gameId']
        self.assertEqual(state['result']['winner'],'white')
        await ws.send_json({'type':'rematch'})
        state=await self.state(ws,lambda g:g['gameId']!=old)
        self.assertEqual(state['moves'],0);self.assertEqual(state['status'],'playing')
        self.assertFalse((await (await self.client.get('/api/lobby')).json())['list'])
        await ws.close()
    async def test_hidden_and_unavailable_outside_preview(self):
        with patch.dict(os.environ,{'GO13_PREVIEW':''}):
            response=await self.client.post('/api/test-match',json={})
            self.assertEqual(response.status,404)
            html=await (await self.client.get('/')).text()
            self.assertIn('id="testMatch" class="button secondary hidden"',html)
