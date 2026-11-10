import unittest
from unittest.mock import patch
import preview_bot as bot
from server import try_move, board_hash

class AILevels(unittest.TestCase):
    def test_high_preserves_existing_opponent(self):
        state={'board':[0]*169}
        with patch.object(bot,'choose_action',return_value={'type':'move','index':42}) as existing:
            self.assertEqual(bot.choose_level_action(state,try_move,board_hash,level='high')['index'],42)
            existing.assert_called_once()

    def test_levels_use_distinct_candidate_ranges_and_legal_moves(self):
        for role in ('black','white'):
            state={'board':[0]*169,'botRole':role}
            sizes=[]
            for level in ('medium','low'):
                def pick(pool):
                    sizes.append(len(pool))
                    return pool[0]
                with patch.object(bot.random,'choice',side_effect=pick):
                    move=bot.choose_level_action(state,try_move,board_hash,level=level)
                try_move(state['board'],move['index'],1 if role=='black' else -1,set())
            self.assertEqual(sizes,[5,169])
