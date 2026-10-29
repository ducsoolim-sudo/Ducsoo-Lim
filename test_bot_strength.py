import random
import time
import unittest
import server as s
from preview_bot import choose_action

class BotTactics(unittest.TestCase):
    def action(self, board, passes=0, ko=None):
        random.seed(17)
        state={'board':board,'passes':passes,'captures':{'black':0,'white':0}}
        return choose_action(state,s.try_move,s.board_hash,ko)

    def test_captures_an_atari_stone(self):
        b=[0]*169;b[84]=1
        for p in (71,83,85):b[p]=-1
        self.assertEqual(self.action(b)['index'],97)

    def test_saves_own_stone_from_atari(self):
        b=[0]*169;b[84]=-1
        for p in (71,83,85):b[p]=1
        self.assertEqual(self.action(b)['index'],97)

    def test_avoids_self_atari(self):
        b=[0]*169
        for p in (71,83,85):b[p]=1
        self.assertNotEqual(self.action(b)['index'],84)

    def test_preserves_own_eye(self):
        b=[0]*169
        for p in (71,83,85,97):b[p]=-1
        self.assertNotEqual(self.action(b)['index'],84)

    def test_does_not_pass_in_an_unfinished_position(self):
        b=[0]*169;b[42]=1
        self.assertEqual(self.action(b,passes=1)['type'],'move')

    def test_respects_forbidden_ko_board(self):
        b=[0]*169;b[84]=1
        for p in (71,83,85):b[p]=-1
        target,_=s.try_move(b,97,-1,set())
        self.assertNotEqual(self.action(b,ko=s.board_hash(target)).get('index'),97)

    def test_settled_double_pass_is_allowed(self):
        b=[1 if p%13<6 else -1 for p in range(169)]
        for p in (0,2,10,12):b[p]=0
        self.assertEqual(self.action(b,passes=1),{'type':'pass'})
