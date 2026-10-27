"""Repeated Find a Match integration scenarios with real HTTP/WebSockets."""
import asyncio
import unittest
from aiohttp.test_utils import TestClient, TestServer
import server as s


class RepeatedMatch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        s.REQUEST_TIMES.clear()
        self.client = TestClient(TestServer(s.make_app(s.RoomStore(path=':memory:', database_url=''))))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def match(self, name):
        response = await self.client.post('/api/match', json={'name': name})
        self.assertEqual(response.status, 200)
        return await response.json()

    async def join(self, player):
        ws = await self.client.ws_connect('/ws')
        await ws.send_json({'type': 'join', **player})
        welcome = await ws.receive_json(timeout=2)
        self.assertEqual(welcome['role'], player['role'])
        await self.state(ws)
        return ws

    async def state(self, ws):
        while True:
            event = await ws.receive_json(timeout=2)
            self.assertNotEqual(event['type'], 'error', event)
            if event['type'] == 'state':
                return event['state']

    async def both(self, a, b):
        left, right = await self.state(a), await self.state(b)
        self.assertEqual(left, right)
        return left

    async def test_ten_matches_moves_reconnect_score_rematch(self):
        rooms = set()
        for run in range(10):
            a, b = await self.match(f'A{run}'), await self.match(f'B{run}')
            self.assertEqual(a['room'], b['room'])
            self.assertNotIn(a['room'], rooms); rooms.add(a['room'])
            self.assertEqual((a['role'], b['role']), ('black', 'white'))
            wa, wb = await self.join(a), await self.join(b)
            await self.state(wa)
            for index in range(8):
                await (wa if index % 2 == 0 else wb).send_json({'type': 'move', 'index': index})
                state = await self.both(wa, wb)
                self.assertEqual(state['moves'], index + 1)
                self.assertEqual(state['board'][index], 1 if index % 2 == 0 else -1)
            await wb.close(); await self.state(wa)
            wb = await self.join(b); await self.state(wa)
            for ws in (wa, wb):
                await ws.send_json({'type': 'pass'}); state = await self.both(wa, wb)
            self.assertEqual(state['status'], 'scoring')
            for ws in (wa, wb):
                await ws.send_json({'type': 'approve'}); state = await self.both(wa, wb)
            self.assertEqual(state['status'], 'finished')
            old_id = state['gameId']
            for ws in (wa, wb):
                await ws.send_json({'type': 'rematch'}); state = await self.both(wa, wb)
            self.assertNotEqual(state['gameId'], old_id)
            self.assertEqual(state['moves'], 0)
            await wa.send_json({'type': 'resign'}); state = await self.both(wa, wb)
            self.assertEqual(state['result']['winner'], 'white')
            await wa.close(); await wb.close()

    async def test_twenty_simultaneous_requests_form_ten_pairs(self):
        players = await asyncio.gather(*(self.match(f'Concurrent{i}') for i in range(20)))
        grouped = {}
        for player in players:
            grouped.setdefault(player['room'], []).append(player['role'])
        self.assertEqual(len(grouped), 10)
        self.assertTrue(all(sorted(roles) == ['black', 'white'] for roles in grouped.values()))

    async def test_ten_cancel_then_search_again(self):
        for i in range(10):
            a = await self.match(f'Cancel{i}')
            wa = await self.join(a)
            await wa.send_json({'type': 'cancel'})
            state = await self.state(wa)
            self.assertEqual(state['status'], 'cancelled')
            b = await self.match(f'Next{i}')
            self.assertNotEqual(a['room'], b['room'])
            wb = await self.join(b)
            await wb.send_json({'type': 'cancel'}); await self.state(wb)
            await wa.close(); await wb.close()
