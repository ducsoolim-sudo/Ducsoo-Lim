"""Automatic adjudication contracts across the real WebSocket lifecycle."""
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
import server as s


def finished_actions():
    goals={1:[row*13+col for row in range(12,-1,-1) for col in range(6) if row*13+col not in (0,2)],
           -1:[row*13+col for row in range(12,-1,-1) for col in range(12,5,-1) if row*13+col not in (10,12)]}
    color=1
    while any(goals.values()):
        yield color, ({'type':'move','index':goals[color].pop(0)} if goals[color] else {'type':'pass'})
        color *= -1
    yield color, {'type':'pass'}
    yield -color, {'type':'pass'}


class AutomaticScoreFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client=TestClient(TestServer(s.make_app(s.RoomStore(path=':memory:',database_url=''))))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def state(self,ws):
        while True:
            message=await ws.receive_json(timeout=3)
            if message['type']=='state':return message['state']

    async def join(self,player):
        ws=await self.client.ws_connect('/ws')
        await ws.send_json({'type':'join',**player})
        self.assertEqual((await ws.receive_json())['type'],'welcome')
        await self.state(ws)
        return ws

    async def test_proven_finish_two_party_confirmation_without_engine(self):
        black=await (await self.client.post('/api/match',json={'name':'A'})).json()
        white=await (await self.client.post('/api/match',json={'name':'B'})).json()
        room=s.ROOMS[black['room']]
        # Build the finish through180 legal actions, never inject the board.
        a=await self.join(black);b=await self.join(white);await self.state(a)
        started=s.time.time()
        for index,(color,action) in enumerate(finished_actions()):
            ws=a if color==1 else b
            # Virtual quarter-second actions keep the real flood limiter enabled.
            with patch('server.time.time',return_value=started+(index+1)*.25):
                await ws.send_json(action)
                left,right=await self.state(a),await self.state(b)
                self.assertEqual(left,right)
        self.assertEqual(left['moves'],180)
        self.assertEqual(left['captures'],{'black':0,'white':0})
        self.assertEqual(left['adjudication']['source'],'Benson pass-alive proof')
        self.assertEqual(left['status'],'scoring')
        self.assertEqual(left['score']['blackTerritory'],2)
        self.assertEqual(left['score']['whiteTerritory'],2)
        self.assertIsNotNone(left['clock']['reviewDeadline'])
        self.assertIsNone(left['clock']['running'])
        await a.send_json({'type':'dead','index':1})
        self.assertEqual((await a.receive_json())['type'],'error')
        self.assertEqual(room.dead,set())
        for ws in (a,b):
            await ws.send_json({'type':'approve'})
            left,right=await self.state(a),await self.state(b)
            self.assertEqual(left,right)
        self.assertEqual(left['status'],'finished')
        self.assertEqual(left['result']['winner'],'white')
        self.assertEqual(left['result']['margin'],6.5)
        self.assertIn('RE[W+6.5]',left['sgf'])
        await a.close();await b.close()

    async def test_empty_double_pass_does_not_create_komi_only_result(self):
        created=await (await self.client.post('/api/rooms',json={'name':'A','solo':True})).json()
        a=await self.join(created)
        for _ in range(2):
            await a.send_json({'type':'pass'});state=await self.state(a)
        self.assertEqual(state['status'],'playing')
        self.assertIsNone(state['score']);self.assertIsNone(state['result'])
        self.assertIn('Continue',state['scoringNotice'])
        await a.close()
