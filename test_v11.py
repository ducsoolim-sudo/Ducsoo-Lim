import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import server as s
from aiohttp.test_utils import TestClient, TestServer


class ClockTests(unittest.TestCase):
    def room(self):
        room=s.Room('CLOCK');room.claim(None,'A');room.claim(None,'B')
        room.time_policy='fischer-v1'  # Compatibility for saved v1.1 games.
        room.turn_started=1000
        return room

    def test_elapsed_increment_and_timeout(self):
        room=self.room()
        with patch('server.time.time',return_value=1010):
            room.act('black',{'type':'move','index':0})
        self.assertEqual(room.remaining,{'black':293,'white':300})
        self.assertEqual(room.turn_started,1010)
        self.assertFalse(room.tick(1309))
        self.assertTrue(room.tick(1310))
        self.assertEqual(room.result,{'reason':'time','winner':'black'})
        self.assertIn('RE[B+T]',room.sgf())

    def test_late_move_cannot_beat_clock(self):
        room=self.room()
        with patch('server.time.time',return_value=1301):
            room.act('black',{'type':'move','index':0})
        self.assertEqual(room.board[0],0)
        self.assertEqual(room.result['winner'],'white')

    def test_scoring_pauses_clock_and_has_review_deadline(self):
        room=self.room()
        with patch('server.time.time',return_value=1001):room.act('black',{'type':'pass'})
        with patch('server.time.time',return_value=1002):room.act('white',{'type':'pass'})
        self.assertIsNone(room.clock(1020)['running'])
        with patch('server.time.time',return_value=1003):room.act('black',{'type':'approve'})
        self.assertTrue(room.tick(1122))
        self.assertEqual(room.result,{'reason':'review_timeout','winner':'black'})

    def test_neither_approves_cancels_without_false_winner(self):
        room=self.room();room.status='scoring';room.review_deadline=1001
        room.tick(1002)
        self.assertEqual(room.status,'cancelled');self.assertIsNone(room.result)

    def test_resume_restarts_clock_and_rematch_resets(self):
        room=self.room();room.status='scoring';room.review_deadline=1100
        with patch('server.time.time',return_value=1002):room.act('white',{'type':'resume'})
        self.assertEqual(room.turn_started,1002);self.assertIsNone(room.review_deadline)
        room.remaining['black']=20
        with patch('server.time.time',return_value=1003):
            room.act('white',{'type':'resign'})
            room.act('black',{'type':'rematch'});room.act('white',{'type':'rematch'})
        self.assertEqual(room.remaining,{'black':300,'white':300})

    def test_disconnect_grace_and_reconnection(self):
        room=self.room()
        class Socket:closed=False
        ws=Socket();room.clients[ws]='white'
        room.absent_since['black']=1000
        self.assertFalse(room.tick(1089));self.assertTrue(room.tick(1090))
        self.assertEqual(room.result,{'reason':'disconnect','winner':'white'})
        room=self.room();room.clients[ws]='black';room.absent_since['black']=1000
        with patch('server.time.time',return_value=1010):room.connection_changed()
        self.assertIsNone(room.absent_since['black'])

    def test_cancel_and_match_race(self):
        room=s.Room('QUEUE',public=True);room.claim(None,'A')
        room.act('black',{'type':'cancel'});self.assertEqual(room.status,'cancelled')
        room=self.room();room.turn_started=None
        with self.assertRaises(ValueError):room.act('black',{'type':'cancel'})
        self.assertEqual(room.status,'playing')

    def test_solo_has_no_clock_or_disconnect_loss(self):
        room=s.Room('SOLO',solo=True);room.claim(None,'A')
        room.absent_since['black']=0
        self.assertIsNone(room.state()['clock']);self.assertFalse(room.tick(1e12))


class DurabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_retains_tokens_board_history_clock_and_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'games.sqlite3')
            store=s.RoomStore(path=path,database_url='');await store.open()
            room=s.Room('RESTART');_,token=room.claim(None,'A');room.claim(None,'B')
            room.act('black',{'type':'move','index':0});room.act('white',{'type':'pass'})
            await store.save(room);await store.close()
            store=s.RoomStore(path=path,database_url='');await store.open()
            restored=s.Room.from_snapshot((await store.load())[0])
            self.assertEqual(restored.claim(token,'A')[0],'black')
            self.assertEqual(restored.board[0],1)
            self.assertEqual(restored.moves,2)
            self.assertIn(';B[aa];W[]',restored.sgf())
            self.assertEqual(restored.history,room.history)
            self.assertEqual(restored.turn_started,room.turn_started)
            restored.act('black',{'type':'resign'});await store.save(restored)
            row=store.connection.execute('SELECT payload FROM go13_games').fetchone()
            self.assertEqual(json.loads(row[0])['result']['reason'],'resign')
            self.assertNotIn(token,row[0])
            await store.close()

    async def test_stale_writer_cannot_overwrite_newer_board(self):
        store=s.RoomStore(path=':memory:',database_url='');await store.open()
        room=s.Room('CAS',solo=True);room.claim(None,'A');await store.save(room)
        stale=s.Room.from_snapshot((await store.load())[0])
        room.act('black',{'type':'move','index':0});await store.save(room)
        stale.act('black',{'type':'move','index':1})
        with self.assertRaises(s.StaleRoom) as raised:await store.save(stale)
        self.assertEqual(raised.exception.snapshot['board'][0],1)
        self.assertEqual((await store.load())[0]['board'][1],0)
        await store.close()

    async def test_websocket_cancel_removes_waiting_room_from_matching(self):
        s.ROOMS.clear();s.REQUEST_TIMES.clear()
        client=TestClient(TestServer(s.make_app(s.RoomStore(path=':memory:',database_url=''))))
        await client.start_server()
        try:
            a=await (await client.post('/api/match',json={'name':'A'})).json()
            ws=await client.ws_connect('/ws');await ws.send_json({'type':'join',**a})
            await ws.receive_json();await ws.receive_json()
            await ws.send_json({'type':'cancel'})
            self.assertEqual((await ws.receive_json())['state']['status'],'cancelled')
            b=await (await client.post('/api/match',json={'name':'B'})).json()
            self.assertNotEqual(a['room'],b['room'])
            await ws.close()
        finally:await client.close()

    async def test_reconnect_retires_old_seat_socket_after_durable_join(self):
        s.ROOMS.clear();s.REQUEST_TIMES.clear()
        store=s.RoomStore(path=':memory:',database_url='')
        client=TestClient(TestServer(s.make_app(store)));await client.start_server()
        try:
            seat=await (await client.post('/api/rooms',json={'solo':True})).json()
            first=await client.ws_connect('/ws');await first.send_json({'type':'join',**seat})
            await first.receive_json();await first.receive_json()
            second=await client.ws_connect('/ws');await second.send_json({'type':'join',**seat})
            self.assertEqual((await second.receive_json(timeout=2))['role'],'black')
            await second.receive_json(timeout=2)
            closed=await first.receive(timeout=2)
            self.assertEqual(closed.type,s.WSMsgType.CLOSE)
            self.assertEqual(closed.data,4001)
            room=s.ROOMS[seat['room']]
            self.assertEqual(list(room.clients.values()),['black'])
            await second.send_json({'type':'move','index':0})
            for _ in range(3):
                state=(await second.receive_json(timeout=2))['state']
                if state['moves']==1:break
            self.assertEqual(state['moves'],1)
            await second.close()
        finally:await client.close()

    async def test_failed_reconnect_keeps_original_seat_connection(self):
        s.ROOMS.clear();s.REQUEST_TIMES.clear()
        store=s.RoomStore(path=':memory:',database_url='')
        client=TestClient(TestServer(s.make_app(store)));await client.start_server()
        try:
            seat=await (await client.post('/api/rooms',json={'solo':True})).json()
            first=await client.ws_connect('/ws');await first.send_json({'type':'join',**seat})
            await first.receive_json();await first.receive_json()
            original=store.save
            async def fail(room):raise RuntimeError('database unavailable')
            store.save=fail
            second=await client.ws_connect('/ws');await second.send_json({'type':'join',**seat})
            self.assertEqual((await second.receive_json(timeout=2))['type'],'error')
            self.assertFalse(first.closed)
            store.save=original
            await first.send_json({'type':'move','index':0})
            self.assertEqual((await first.receive_json(timeout=2))['state']['moves'],1)
            await first.close();await second.close()
        finally:await client.close()

    async def test_failed_storage_rolls_back_unacknowledged_move(self):
        s.ROOMS.clear();s.REQUEST_TIMES.clear()
        store=s.RoomStore(path=':memory:',database_url='')
        client=TestClient(TestServer(s.make_app(store)));await client.start_server()
        try:
            a=await (await client.post('/api/rooms',json={'solo':True})).json()
            ws=await client.ws_connect('/ws');await ws.send_json({'type':'join',**a})
            await ws.receive_json();await ws.receive_json()
            original=store.save
            async def fail(room):raise RuntimeError('database unavailable')
            store.save=fail
            await ws.send_json({'type':'move','index':0})
            self.assertEqual((await ws.receive_json())['type'],'error')
            self.assertEqual(s.ROOMS[a['room']].moves,0)
            self.assertEqual(s.ROOMS[a['room']].board[0],0)
            store.save=original
            await ws.send_json({'type':'move','index':0})
            self.assertEqual((await ws.receive_json())['state']['moves'],1)
            await ws.close()
        finally:await client.close()


class SoloIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_solo_alternates_over_websocket_and_reconnect(self):
        s.ROOMS.clear();s.REQUEST_TIMES.clear()
        client=TestClient(TestServer(s.make_app(s.RoomStore(path=':memory:',database_url=''))))
        await client.start_server()
        try:
            seat=await (await client.post('/api/rooms',json={'solo':True})).json()
            ws=await client.ws_connect('/ws');await ws.send_json({'type':'join',**seat})
            welcome=await ws.receive_json();await ws.receive_json()
            self.assertEqual(welcome['role'],'black')
            for i in range(8):
                await ws.send_json({'type':'move','index':i})
                message=await ws.receive_json();self.assertEqual(message['type'],'state')
                state=message['state']
                self.assertEqual(state['board'][:i+1],[1 if j%2==0 else -1 for j in range(i+1)])
                self.assertEqual(state['turn'],'white' if i%2==0 else 'black')
            await ws.close()
            ws=await client.ws_connect('/ws');await ws.send_json({'type':'join',**seat})
            await ws.receive_json();state=(await ws.receive_json())['state']
            self.assertEqual(state['moves'],8)
            await ws.send_json({'type':'pass'});self.assertEqual((await ws.receive_json())['state']['turn'],'white')
            await ws.send_json({'type':'move','index':20});state=(await ws.receive_json())['state']
            self.assertEqual(state['board'][20],-1);self.assertEqual(state['turn'],'black')
            await ws.close()
        finally:await client.close()

if __name__=='__main__':unittest.main()
