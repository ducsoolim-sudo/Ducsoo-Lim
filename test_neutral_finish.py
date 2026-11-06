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
