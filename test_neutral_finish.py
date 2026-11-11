import unittest
from unittest.mock import patch,AsyncMock
import server as s
import strong_bot
from scoring import territory_score


def complete_with_dame():
    board=[1 if p%13<6 else -1 for p in range(169)]
    for point in (0,2,10,12,83):board[point]=0
    return board

class NeutralFinish(unittest.IsolatedAsyncioTestCase):
    async def test_engine_passes_proven_finish_without_search(self):
        state={'board':complete_with_dame(),'captures':{'black':0,'white':0}}
        with patch.object(strong_bot._ENGINE,'query',new_callable=AsyncMock) as query:
            self.assertEqual(await strong_bot.choose_action(state,s.try_move,s.board_hash),{'type':'pass'})
            query.assert_not_awaited()
    async def test_both_passes_reach_confirmation_and_result(self):
        room=s.Room('DAME');room.claim(None,'A');room.claim(None,'B')
        room.board=complete_with_dame();room.moves=20
        room.act('black',{'type':'pass'});room.act('white',{'type':'pass'})
        self.assertEqual(room.status,'scoring');self.assertEqual(room.adjudication['status'],'ready')
        self.assertFalse(room.score_uncertain)
        self.assertEqual(room.calculate_score()['neutral'],1)
        room.act('black',{'type':'approve'});room.act('white',{'type':'approve'})
        self.assertEqual(room.status,'finished');self.assertEqual(room.result['margin'],6.5)
    async def test_shared_liberty_does_not_erase_proven_eyes(self):
        score=territory_score(complete_with_dame(),set(),{'black':0,'white':0})
        self.assertEqual((score['blackTerritory'],score['whiteTerritory'],score['neutral']),(2,2,1))


class PassComparison(unittest.IsolatedAsyncioTestCase):
    def state(self, role='white', passes=1):
        board=[0]*169;board[42]=1;board[126]=-1
        return dict(board=board,captures={'black':0,'white':0},botRole=role,
                    passes=passes,moves=3,sgf='(;SZ[13];B[dd];W[jj];B[])')

    async def test_human_pass_gets_reply_when_continuing_gains_nothing(self):
        for role, best, passed in [('white',-6.2,-6.0),('black',6.2,6.0)]:
            state=self.state(role)
            search={'moveInfos':[{'move':'D4','order':0}], 'rootInfo':{'scoreLead':best}}
            finish={'moveInfos':[{'move':'pass','order':0}], 'rootInfo':{'scoreLead':passed}}
            with patch.object(strong_bot,'settings',return_value=('engine','model')), patch.object(strong_bot._ENGINE,'query',new_callable=AsyncMock,side_effect=[search,finish]) as query:
                self.assertEqual(await strong_bot.choose_action(state,s.try_move,s.board_hash),{'type':'pass'})
                forced=query.await_args_list[1].args[2]
                self.assertEqual(forced['allowMoves'],[{'player':'B' if role=='black' else 'W','moves':['pass'],'untilDepth':1}])
                self.assertGreaterEqual(forced['maxVisits'],64)

    async def test_unfinished_position_retains_profitable_move(self):
        state=self.state()
        search={'moveInfos':[{'move':'D4','order':0}], 'rootInfo':{'scoreLead':-6}}
        finish={'moveInfos':[{'move':'pass','order':0}], 'rootInfo':{'scoreLead':-2}}
        with patch.object(strong_bot,'settings',return_value=('engine','model')), patch.object(strong_bot._ENGINE,'query',new_callable=AsyncMock,side_effect=[search,finish]):
            self.assertEqual((await strong_bot.choose_action(state,s.try_move,s.board_hash))['type'],'move')

    def test_uncertain_or_missing_pass_scores_do_not_force_finish(self):
        best={'rootInfo':{'scoreLead':6}}
        for passed in ({}, {'rootInfo':{'scoreLead':float('nan')}}, {'rootInfo':{'scoreLead':6,'noResultProb':.1}}):
            self.assertFalse(strong_bot.pass_is_equivalent(best,passed,self.state('black')))

    def test_engine_order_is_respected_even_if_list_order_differs(self):
        result={'moveInfos':[{'move':'D4','order':2},{'move':'pass','order':0}]}
        self.assertEqual(strong_bot.select_action(result,self.state(),s.try_move,s.board_hash),{'type':'pass'})
