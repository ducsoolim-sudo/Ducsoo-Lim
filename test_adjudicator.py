import asyncio
import copy
import unittest
from unittest.mock import AsyncMock
import server as s
from adjudicator import adjudicate, validated, query, KataGo, settled_adjudication
from aiohttp.test_utils import TestClient, TestServer


def result(owner, lead, dev=None):
    return {'ownership':owner,'ownershipStdev':dev or [0.01]*169,'rootInfo':{'scoreLead':lead}}


class AdjudicationTests(unittest.TestCase):
    def test_stable_territory_and_dead_group(self):
        board=[1]*169; board[0]=board[2]=0; board[84]=-1
        r=result([.99]*169,-2.5)  # 3 territory + 1 prisoner - 6.5 komi
        answer=adjudicate(board,{'black':0,'white':0},r,r)
        self.assertEqual(answer['dead'],[84]);self.assertEqual(answer['status'],'ready')
        self.assertEqual(answer['score']['black'],4)

    def test_seki_eyes_neutral_stones_survive(self):
        board=[1 if i%13<6 else -1 for i in range(169)]
        board[0]=board[12]=0
        owner=[.99 if c==1 else -.99 if c==-1 else 0 for c in board]
        r=result(owner,-6.5)
        answer=adjudicate(board,{'black':0,'white':0},r,r)
        self.assertFalse(answer['dead']);self.assertEqual(answer['status'],'ready')
        self.assertEqual(answer['score']['blackTerritory'],0)
        self.assertEqual(answer['score']['whiteTerritory'],0)

    def test_ko_disagreement_requires_review(self):
        board=[1]*169;board[84]=-1
        a=result([.99]*169,-4.5);b=result([.99]*169,-4.5)
        b['ownership'][84]=-.99
        self.assertEqual(adjudicate(board,{'black':0,'white':0},a,b)['status'],'review')

    def test_low_confidence_and_score_disagreement_block(self):
        board=[1]*169
        a=result([.99]*169,-6.5)
        for changed in (result([.5]*169,-6.5),result([.99]*169,3.5)):
            self.assertEqual(adjudicate(board,{'black':0,'white':0},a,changed)['status'],'review')

    def test_possible_no_result_never_becomes_a_win(self):
        board=[1]*169
        a=result([.99]*169,-6.5)
        a['rootInfo']['rawNoResultProb']=.2
        answer=adjudicate(board,{'black':0,'white':0},a,a)
        self.assertEqual(answer['status'],'review')
        self.assertIn('possible_no_result',answer['reasons'])
        a['rootInfo']['rawNoResultProb']=float('nan')
        with self.assertRaises(ValueError):validated(a)

    def test_bad_engine_results_rejected(self):
        for value in (float('nan'),float('inf'),2):
            r=result([.99]*169,-6.5);r['ownership'][0]=value
            with self.assertRaises(ValueError):validated(r)
        r=result([0]*169,0);r['warning']='unsupported rules'
        with self.assertRaises(ValueError):validated(r)

    def test_preserves_moves_and_ko_history_trims_only_trailing_passes(self):
        room=s.Room('QUERY');room.move_record=[(1,0),(-1,None),(1,14),(-1,None),(1,None)]
        request=query(room,'test',1024)
        self.assertEqual(request['moves'],[['B','A13'],['W','pass'],['B','B12']])
        self.assertEqual(request['rules'],'japanese')


class SettledProofTests(unittest.TestCase):
    def finished_board(self):
        board = [1 if i % 13 < 6 else -1 for i in range(169)]
        for p in (0, 2, 10, 12):
            board[p] = 0
        return board

    def test_two_proven_living_sides_exact_territory_prisoners_and_komi(self):
        verdict = settled_adjudication(self.finished_board(), {'black': 5, 'white': 1})
        self.assertEqual(verdict['status'], 'ready')
        self.assertEqual(verdict['score']['blackTerritory'], 2)
        self.assertEqual(verdict['score']['whiteTerritory'], 2)
        self.assertEqual(verdict['score']['black'], 7)
        self.assertEqual(verdict['score']['white'], 9.5)
        self.assertEqual(verdict['score']['margin'], 2.5)
        self.assertEqual(verdict['score']['winner'], 'white')

    def test_small_dead_group_does_not_bypass_specialist_review(self):
        board = self.finished_board(); board[42] = -1; board[43] = 0
        self.assertIsNone(settled_adjudication(board, {'black': 0, 'white': 0}))

    def test_unfilled_dame_still_needs_play_or_specialist_review(self):
        board = self.finished_board(); board[6*13+5] = 0
        self.assertIsNone(settled_adjudication(board, {'black': 0, 'white': 0}))

    def test_seki_unfinished_and_empty_positions_do_not_use_fast_path(self):
        for board in ([0]*169, [1]+[0]*167+[-1]):
            self.assertIsNone(settled_adjudication(board, {'black': 0, 'white': 0}))
        board = self.finished_board()
        board[2] = 1; board[10] = -1
        board[6*13+5] = 0; board[7*13+6] = 0
        self.assertIsNone(settled_adjudication(board, {'black': 0, 'white': 0}))

    def test_rotation_preserves_exact_result(self):
        board = self.finished_board()
        self.assertEqual(settled_adjudication(board, {'black': 3, 'white': 2})['score'],
                         settled_adjudication(board[::-1], {'black': 3, 'white': 2})['score'])

    def test_invalid_board_rejected(self):
        with self.assertRaises(ValueError):settled_adjudication([0]*168, {'black': 0, 'white': 0})


class SettledEngineBypass(unittest.IsolatedAsyncioTestCase):
    async def test_proven_finish_does_not_start_model_or_subprocess(self):
        from types import SimpleNamespace
        board = SettledProofTests().finished_board()
        engine = KataGo(); engine.binary=''; engine.model=''; engine.run=AsyncMock()
        verdict=await engine.analyze(SimpleNamespace(board=board,captures={'black':0,'white':0}))
        self.assertEqual(verdict['status'],'ready');engine.run.assert_not_awaited()


class EngineLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client=TestClient(TestServer(s.make_app(s.RoomStore(path=':memory:',database_url=''))))
        await self.client.start_server();self.app=self.client.server.app
        self.app[s.ENGINE].binary='configured';self.app[s.ENGINE].model='configured'
        self.room=s.Room('ASYNC',solo=True);self.room.claim(None,'A')
        self.room.act('black',{'type':'pass'});self.room.act('black',{'type':'pass'})
        s.ROOMS[self.room.code]=self.room

    async def asyncTearDown(self):await self.client.close()

    async def test_pending_blocks_approval_failure_has_no_forfeit(self):
        self.app[s.ENGINE].analyze=AsyncMock(side_effect=RuntimeError('engine failed'))
        s.schedule_adjudication(self.app,self.room)
        with self.assertRaises(ValueError):self.room.act('black',{'type':'approve'})
        with self.assertLogs(level="ERROR"):
            await asyncio.gather(*self.app[s.JOBS])
        self.assertEqual(self.room.status,'playing')
        self.assertIsNone(self.room.result)
        self.assertIsNone(self.room.adjudication)
        self.assertTrue(self.room.scoring_notice)
        self.assertIsNone(self.room.review_deadline)
        with self.assertRaises(ValueError):self.room.act('black',{'type':'approve'})

    async def test_resume_discards_stale_analysis(self):
        gate=asyncio.Event()
        async def delayed(room):
            await gate.wait()
            return {'status':'ready','dead':[],'uncertain':[],'score':room.calculate_score()}
        self.app[s.ENGINE].analyze=delayed
        s.schedule_adjudication(self.app,self.room)
        self.room.act('black',{'type':'resume'})
        gate.set();await asyncio.gather(*self.app[s.JOBS])
        self.assertEqual(self.room.status,'playing');self.assertIsNone(self.room.adjudication)

    async def test_ready_result_is_saved_and_can_be_confirmed(self):
        score=self.room.calculate_score()
        self.app[s.ENGINE].analyze=AsyncMock(return_value={'status':'ready','dead':[],'uncertain':[],'score':score})
        s.schedule_adjudication(self.app,self.room)
        await asyncio.gather(*self.app[s.JOBS])
        self.room.act('black',{'type':'approve'})
        self.assertEqual(self.room.status,'finished')
        stored=await self.app[s.STORE].load()
        self.assertEqual(stored[0]['adjudication']['status'],'ready')
