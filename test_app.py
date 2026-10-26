import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
import server as s
from aiohttp.test_utils import TestClient, TestServer

class Rules(unittest.TestCase):
    def test_rematch_has_new_game_id(self):
        r=self.room();old=r.game_id;r.act('black',{'type':'resign'});r.act('black',{'type':'rematch'})
        self.assertNotEqual(old,r.game_id)
        self.assertEqual(r.state()['gameId'],r.game_id)
    def test_pass_then_move_resets_sequence(self):
        r=self.room(False);r.act('black',{'type':'pass'});self.assertEqual(r.passes,1)
        r.act('white',{'type':'move','index':84});self.assertEqual(r.passes,0)
        r.act('black',{'type':'pass'});self.assertEqual(r.status,'playing')
        r.act('white',{'type':'pass'});self.assertEqual(r.status,'scoring')
    def test_same_player_cannot_pass_twice(self):
        r=self.room(False);r.act('black',{'type':'pass'})
        with self.assertRaises(ValueError):r.act('black',{'type':'pass'})
        self.assertEqual((r.passes,r.status),(1,'playing'))
    def room(self, solo=True):
        r=s.Room('TEST', solo=solo); r.claim(None,'Tester')
        if not solo: r.claim(None,'Other')
        return r
    def test_alternating(self):
        r=self.room(); r.act('black',{'type':'move','index':0}); r.act('black',{'type':'move','index':1})
        self.assertEqual(r.board[:2],[1,-1])
    def test_occupied(self):
        r=self.room(); r.act('black',{'type':'move','index':0})
        with self.assertRaises(ValueError): r.act('black',{'type':'move','index':0})
    def test_suicide(self):
        b=[0]*169;b[1]=b[13]=-1
        with self.assertRaises(ValueError): s.try_move(b,0,1,set())
    def test_capture(self):
        b=[0]*169;b[0]=-1;b[1]=1
        result,n=s.try_move(b,13,1,set());self.assertEqual((result[0],n),(0,1))
    def test_repetition(self):
        b=[0]*169; result,_=s.try_move(b,0,1,set())
        with self.assertRaises(ValueError): s.try_move(b,0,1,{s.board_hash(result)})
    def test_scoring_and_rematch(self):
        r=self.room();r.act('black',{'type':'pass'});r.act('black',{'type':'pass'});self.assertEqual(r.status,'scoring')
        r.act('black',{'type':'approve'});self.assertEqual(r.status,'finished')
        r.act('black',{'type':'rematch'});self.assertEqual((r.status,r.moves),('playing',0))
    def test_resume(self):
        r=self.room();r.act('black',{'type':'pass'});r.act('black',{'type':'pass'});r.act('black',{'type':'resume'});self.assertEqual(r.status,'playing')
    def test_resign_white_turn(self):
        r=self.room();r.act('black',{'type':'move','index':0});r.act('black',{'type':'resign'});self.assertEqual(r.result['winner'],'black')
    def test_solo_private_and_owner(self):
        r=s.Room('TEST',public=True,solo=True);_,token=r.claim(None,'Owner')
        self.assertFalse(r.public);self.assertEqual(r.claim(None,'Intruder')[0],'spectator');self.assertEqual(r.claim(token,'Owner')[0],'black')
        with self.assertRaises(ValueError): r.act('white',{'type':'move','index':0})
    def test_normal_turn(self):
        r=self.room(False)
        with self.assertRaises(ValueError):r.act('white',{'type':'move','index':0})
        r.act('black',{'type':'move','index':0});r.act('white',{'type':'move','index':1});self.assertEqual(r.moves,2)
    def test_spectator(self):
        with self.assertRaises(ValueError):self.room().act('spectator',{'type':'move','index':0})
    def test_normal_agreement(self):
        r=self.room(False);r.act('black',{'type':'pass'});r.act('white',{'type':'pass'});r.act('black',{'type':'approve'});self.assertEqual(r.status,'scoring');r.act('white',{'type':'approve'});self.assertEqual(r.status,'finished')

class API(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        s.ROOMS.clear();s.REQUEST_TIMES.clear();s.ROOT.joinpath('static').mkdir(exist_ok=True)
        s.ROOT.joinpath('static/index.html').write_text(s.ROOT.joinpath('index.html').read_text(encoding='utf-8'),encoding='utf-8')
        self.client=TestClient(TestServer(s.make_app()));await self.client.start_server()
    async def asyncTearDown(self):await self.client.close()
    async def test_health_and_home(self):
        self.assertTrue((await (await self.client.get('/health')).json())['ok'])
        html=await (await self.client.get('/')).text();self.assertIn('13GO',html);self.assertIn('id="solo"',html);self.assertNotIn('十三',html)
        import re
        self.assertIsNone(re.search('[가-힣]',html))
        self.assertNotIn('id="create"',html)
        self.assertIn('My Page',html);self.assertIn('Watch',html)
    async def test_spectator_cannot_play(self):
        created=await (await self.client.post('/api/match',json={'name':'Player'})).json()
        ws=await self.client.ws_connect('/ws');await ws.send_json({'type':'join','room':created['room'],'mode':'watch'})
        self.assertEqual((await ws.receive_json())['role'],'spectator');state=(await ws.receive_json())['state'];self.assertIsNone(state['players']['white'])
        await ws.send_json({'type':'move','index':0});error=await ws.receive_json();self.assertEqual(error['type'],'error');self.assertIn('Spectators',error['message'])
        self.assertEqual(s.ROOMS[created['room']].moves,0);await ws.close()
    async def test_match_and_lobby(self):
        a=await (await self.client.post('/api/match',json={'name':'A'})).json();b=await (await self.client.post('/api/match',json={'name':'B'})).json()
        self.assertEqual(a['room'],b['room']);self.assertEqual(b['role'],'white')
        lobby=await (await self.client.get('/api/lobby')).json();self.assertEqual(lobby['playing'],1)
    async def test_two_players_reconnect_score_and_sgf(self):
        a=await (await self.client.post('/api/match',json={'name':'A]\\test'})).json()
        b=await (await self.client.post('/api/match',json={'name':'B'})).json()
        async def join(player):
            ws=await self.client.ws_connect('/ws')
            await ws.send_json({'type':'join',**player})
            welcome=await ws.receive_json()
            self.assertEqual(welcome['role'],player['role'])
            await ws.receive_json()
            return ws
        async def state(ws):
            while True:
                event=await ws.receive_json(timeout=2)
                if event['type']=='state':return event['state']
        wa=await join(a);wb=await join(b);await state(wa)
        for ws,action in ((wa,{'type':'move','index':0}), (wb,{'type':'move','index':14}), (wa,{'type':'pass'}), (wb,{'type':'pass'})):
            await ws.send_json(action)
            left,right=await state(wa),await state(wb)
            self.assertEqual(left,right)
        self.assertEqual(left['status'],'scoring')
        await wa.close();await state(wb)
        wa=await join(a);await state(wb)
        for ws in (wa,wb):
            await ws.send_json({'type':'approve'})
            left,right=await state(wa),await state(wb)
            self.assertEqual(left,right)
        self.assertEqual(left['status'],'finished')
        self.assertIn(';B[aa];W[bb];B[];W[]',left['sgf'])
        self.assertIn('RE[',left['sgf'])
        self.assertIn('PB[A\\]\\\\test]',left['sgf'])
        for ws in (wa,wb):
            await ws.send_json({'type':'rematch'})
            left,right=await state(wa),await state(wb)
        self.assertEqual(left['moves'],0)
        self.assertNotIn(';B[',left['sgf'])
        await wa.close();await wb.close()
    async def test_solo_websocket(self):
        created=await (await self.client.post('/api/rooms',json={'solo':True,'public':True})).json()
        ws=await self.client.ws_connect('/ws');await ws.send_json({'type':'join',**created})
        self.assertEqual((await ws.receive_json())['role'],'black');state=(await ws.receive_json())['state'];self.assertTrue(state['solo']);self.assertEqual(state['status'],'playing')
        for i in range(2):
            await ws.send_json({'type':'move','index':i});state=(await ws.receive_json())['state']
        self.assertEqual(state['board'][:2],[1,-1]);self.assertEqual((await (await self.client.get('/api/lobby')).json())['list'],[])
        await ws.close()

if __name__=='__main__':unittest.main(verbosity=2)
