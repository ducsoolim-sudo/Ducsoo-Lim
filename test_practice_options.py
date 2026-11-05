import os,unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
import server as s
import strong_bot

class Endgame(unittest.TestCase):
    def test_engine_pass_does_not_require_final_score_proof(self):
        state={'board':[0]*169,'captures':{'black':0,'white':0}}
        self.assertEqual(strong_bot.select_action({'moveInfos':[{'move':'pass'},{'move':'D4'}]},state,s.try_move,s.board_hash),{'type':'pass'})
    def test_fallback_passes_instead_of_filling_finished_territory(self):
        from preview_bot import choose_action
        board=[1 if p%13<6 else -1 for p in range(169)]
        for p in (0,2,10,12):board[p]=0
        self.assertEqual(choose_action({"board":board,"passes":0,"captures":{"black":0,"white":0}},s.try_move,s.board_hash),{"type":"pass"})

    def test_black_engine_move_uses_black_stone(self):
        state={'board':[0]*169,'botRole':'black','captures':{'black':0,'white':0}}
        def play(board,index,color,forbidden):
            self.assertEqual(color,1);return s.try_move(board,index,color,forbidden)
        self.assertEqual(strong_bot.select_action({'moveInfos':[{'move':'D4'}]},state,play,s.board_hash)['type'],'move')

class PracticeColors(unittest.IsolatedAsyncioTestCase):
    async def test_white_human_gets_black_ai_opening(self):
        with patch.dict(os.environ,{'GO13_PREVIEW':'true'}),patch('preview_bot.strong_bot.configured',return_value=False):
            client=TestClient(TestServer(s.make_app(s.RoomStore(path=':memory:',database_url=''))))
            await client.start_server()
            try:
                response=await client.post('/api/test-match',json={'color':'white'})
                self.assertEqual(response.status,200);player=await response.json();self.assertEqual(player['role'],'white')
                ws=await client.ws_connect('/ws');await ws.send_json({'type':'join',**player})
                self.assertEqual((await ws.receive_json())['role'],'white')
                while True:
                    event=await ws.receive_json(timeout=5)
                    self.assertNotEqual(event['type'],'error',event)
                    if event['type']=='state' and event['state']['moves']==1:
                        state=event['state'];self.assertEqual(state['turn'],'white');self.assertEqual(state['board'].count(1),1);self.assertEqual(state['board'].count(-1),0);break
                await ws.send_json({'type':'resign'})
                await ws.close()
                response=await client.post('/api/test-match',json={'color':'bad'})
                self.assertEqual(response.status,400)
            finally:await client.close()
