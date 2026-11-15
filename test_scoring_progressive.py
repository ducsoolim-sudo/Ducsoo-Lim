import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import adjudicator
import strong_bot
import preview_bot
import server


class ProgressiveScoring(unittest.IsolatedAsyncioTestCase):
    def room(self):
        board = [0]*169
        board[0], board[168] = 1, -1
        return SimpleNamespace(board=board, captures={'black':0,'white':0},
                               move_record=[(1,0),(-1,168)])

    def scorer(self):
        scorer=adjudicator.KataGo()
        scorer.binary, scorer.model='engine','model'
        return scorer

    async def test_stable_two_readings_skip_expensive_search(self):
        scorer=self.scorer()
        scorer.run=AsyncMock(return_value={'quick':{'reading':1},'deep':{'reading':2}})
        with patch.object(adjudicator,'adjudicate',return_value={'status':'ready'}) as judge:
            self.assertEqual((await scorer.analyze(self.room()))['status'],'ready')
        self.assertEqual(scorer.run.await_count,1)
        self.assertEqual([q['maxVisits'] for q in scorer.run.await_args.args[0]],[32,128])
        self.assertEqual(judge.call_args.args[2:],({'reading':1},{'reading':2}))

    async def test_uncertainty_refines_and_rechecks_both_readings(self):
        scorer=self.scorer()
        scorer.run=AsyncMock(side_effect=[{'quick':{'reading':1},'deep':{'reading':2}},
                                         {'refined':{'reading':3}}])
        with patch.object(adjudicator,'adjudicate',side_effect=[{'status':'review'}, {'status':'ready'}]) as judge:
            self.assertEqual((await scorer.analyze(self.room()))['status'],'ready')
        self.assertEqual(scorer.run.await_args.args[0][0]['maxVisits'],256)
        self.assertEqual(judge.call_args.args[2:],({'reading':2},{'reading':3}))

    async def test_unresolved_position_stays_review(self):
        scorer=self.scorer()
        scorer.run=AsyncMock(side_effect=[{'quick':{},'deep':{}},{'refined':{}}])
        with patch.object(adjudicator,'adjudicate',return_value={'status':'review'}):
            self.assertEqual((await scorer.analyze(self.room()))['status'],'review')

    async def test_broadly_unsettled_board_skips_expensive_refinement(self):
        scorer=self.scorer()
        scorer.run=AsyncMock(return_value={'quick':{},'deep':{}})
        with patch.object(adjudicator,'adjudicate',return_value={'status':'review','unsettledPoints':85}):
            self.assertEqual((await scorer.analyze(self.room()))['status'],'review')
        self.assertEqual(scorer.run.await_count,1)

    def test_uncertainty_count_precedes_global_score_disagreement(self):
        board=[1]*169;board[0]=0
        stable={'ownership':[.99]*169,'ownershipStdev':[.01]*169,'rootInfo':{'scoreLead':100}}
        verdict=adjudicator.adjudicate(board,{'black':0,'white':0},stable,stable)
        self.assertEqual(verdict['status'],'review')
        self.assertEqual(verdict['unsettledPoints'],0)
        self.assertEqual(len(verdict['uncertain']),169)

    async def test_all_stages_share_one_deadline(self):
        scorer=self.scorer();scorer.timeout=.02
        async def hung(_):
            await asyncio.Event().wait()
        scorer.run=hung
        with self.assertRaises(TimeoutError):
            await scorer.analyze(self.room())


class HumanFinishRequest(unittest.IsolatedAsyncioTestCase):
    async def test_first_human_pass_in_ai_game_avoids_all_engine_search(self):
        for role, record in [('white',';B[aa];W[bb];B[]'),('black',';B[aa];W[]')]:
            state=dict(testBot=True,passes=1,botRole=role,sgf='(;SZ[13]'+record+')')
            with patch.object(strong_bot._ENGINE,'query',new_callable=AsyncMock) as query:
                self.assertEqual(await strong_bot.choose_action(state,None,None),{'type':'pass'})
                self.assertEqual(preview_bot.choose_action(state,None,None),{'type':'pass'})
                query.assert_not_awaited()

    def test_wrong_turn_old_pass_and_human_game_are_not_finish_requests(self):
        for values in ({'passes':0}, {'sgf':'(;B[];W[bb])'},
                       {'sgf':'(;B[aa];W[])'}, {'testBot':False}):
            state=dict(testBot=True,passes=1,botRole='white',sgf='(;B[aa];W[bb];B[])')
            state.update(values)
            self.assertFalse(strong_bot.opponent_requested_finish(state))

    def test_unsettled_review_is_not_relabelled_as_engine_failure(self):
        room=server.Room('REVIEW');room.test_bot=True;room.status='scoring'
        room.adjudication={'status':'review','reasons':['ownership_uncertain']}
        server.continue_unsettled(room,'unsettled')
        self.assertEqual(room.adjudication['status'],'review')
        self.assertIsNone(room.result)
        self.assertIsNone(room.review_deadline)

    async def test_warmup_prepares_real_engine_opening(self):
        with patch.object(strong_bot,'settings',return_value=('engine','model')), \
             patch.object(strong_bot._ENGINE,'query',new_callable=AsyncMock) as query:
            await strong_bot.warmup()
        self.assertEqual(query.await_args.args[2]['maxVisits'],16)

    async def test_prepared_opening_survives_process_restart_without_new_search(self):
        state=dict(moves=0,botRole='black',passes=0,sgf='(;SZ[13])',board=[0]*169,captures={'black':0,'white':0})
        prepared={'moveInfos':[{'move':'D10','order':0}]}
        with patch.dict(strong_bot._OPENINGS,{('engine','model',16):prepared},clear=True), \
             patch.object(strong_bot,'settings',return_value=('engine','model')), \
             patch.object(strong_bot._ENGINE,'query',new_callable=AsyncMock) as query:
            self.assertEqual(await strong_bot.choose_action(state,server.try_move,server.board_hash),{'type':'move','index':42})
            query.assert_not_awaited()

    async def test_opening_cache_is_never_used_on_an_occupied_board(self):
        state=dict(moves=1,botRole='white',passes=0,sgf='(;SZ[13];B[dd])',board=[0]*169,captures={'black':0,'white':0})
        state['board'][42]=1
        response={'moveInfos':[{'move':'K4','order':0}]}
        with patch.dict(strong_bot._OPENINGS,{('engine','model',16):{'moveInfos':[{'move':'D10','order':0}]}},clear=True), \
             patch.object(strong_bot,'settings',return_value=('engine','model')), \
             patch.object(strong_bot._ENGINE,'query',new_callable=AsyncMock,return_value=response) as query:
            self.assertEqual((await strong_bot.choose_action(state,server.try_move,server.board_hash))['index'],126)
            query.assert_awaited_once()


if __name__=='__main__':unittest.main()
