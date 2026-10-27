"""KataGo-assisted adjudication; estimates never bypass uncertainty checks."""
import asyncio
import json
import math
import os
from pathlib import Path
from scoring import group, regions, territory_score

ROOT = Path(__file__).resolve().parent


def coordinate(index):
    return 'ABCDEFGHJKLMNOPQRST'[index % 13] + str(13-index//13)


def query(room, ident, visits):
    moves = list(room.move_record)
    while moves and moves[-1][1] is None:
        moves.pop()
    return dict(id=ident, moves=[['B' if c == 1 else 'W', 'pass' if p is None else coordinate(p)] for c,p in moves],
                rules='japanese', komi=6.5, boardXSize=13, boardYSize=13,
                includeOwnership=True, includeOwnershipStdev=True, maxVisits=visits,
                overrideSettings={'reportAnalysisWinratesAs':'BLACK'})


def validated(result):
    if result.get('error') or result.get('warnings') or result.get('warning'):
        raise ValueError('Engine rejected or changed the requested rules')
    owner, deviation = result.get('ownership'), result.get('ownershipStdev')
    if not isinstance(owner, list) or not isinstance(deviation, list) or len(owner) != 169 or len(deviation) != 169:
        raise ValueError('Incomplete engine ownership')
    if any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1.001 for v in owner):
        raise ValueError('Invalid ownership values')
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 or v>1.001 for v in deviation):
        raise ValueError('Invalid ownership uncertainty')
    root = result.get('rootInfo', {})
    for key in ('noResultProb', 'rawNoResultProb'):
        probability = root.get(key, 0)
        if type(probability) not in (int,float) or not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError('Invalid no-result probability')
    lead = root.get('scoreLead')
    if type(lead) not in (int,float) or not math.isfinite(lead):
        raise ValueError('Invalid engine score')
    return owner, deviation, lead


def adjudicate(board, captures, first, second):
    a, sa, lead_a = validated(first)
    b, sb, lead_b = validated(second)
    dead, uncertain, seki, seen = set(), set(), set(), set()
    reasons = []
    def stable(points, sign):
        return all(sign*a[p]>=.95 and sign*b[p]>=.95 and sa[p]<=.12 and sb[p]<=.12 and abs(a[p]-b[p])<=.08 for p in points)
    for i, color in enumerate(board):
        if not color or i in seen:
            continue
        stones, _ = group(board,i); seen.update(stones)
        if stable(stones,-color):
            dead.update(stones)
        elif stable(stones,color):
            pass
        elif all(abs(a[p])<=.12 and abs(b[p])<=.12 and sa[p]<=.12 and sb[p]<=.12 for p in stones):
            # Neutral ownership alone is not proof of seki: retain for review.
            seki.update(stones); uncertain.update(stones)
        else:
            uncertain.update(stones)
    clean = [0 if i in dead else c for i,c in enumerate(board)]
    territory = {1:0,-1:0}; neutral = 0
    for points, border in regions(clean):
        colors = {clean[p] for p in border}
        if len(colors)==1 and stable(points,next(iter(colors))):
            territory[next(iter(colors))] += len(points)
        elif all(abs(a[p])<=.12 and abs(b[p])<=.12 and sa[p]<=.12 and sb[p]<=.12 for p in points):
            neutral += len(points)
        else:
            neutral += len(points); uncertain.update(points)
    score = territory_score(board,dead,captures)
    score['blackTerritory'],score['whiteTerritory'] = territory[1],territory[-1]
    score['black'] = territory[1]+score['blackPrisoners']
    score['white'] = territory[-1]+score['whitePrisoners']+6.5
    score['winner'] = 'black' if score['black']>score['white'] else 'white'
    score['margin'] = abs(score['black']-score['white']);score['neutral']=neutral
    exact_lead = score['black']-score['white']
    if abs(lead_a-lead_b)>.75 or abs(lead_b-exact_lead)>.75:
        reasons.append('score_disagreement')
        uncertain.update(range(169))
    if any(max(r.get('rootInfo',{}).get('noResultProb',0), r.get('rootInfo',{}).get('rawNoResultProb',0))>.01 for r in (first,second)):
        reasons.append('possible_no_result')
        uncertain.update(range(169))
    if uncertain and not reasons:
        reasons.append('ownership_uncertain')
    return dict(dead=sorted(dead),uncertain=sorted(uncertain),seki=sorted(seki),score=score,
                status='review' if uncertain else 'ready',source='KataGo',reasons=reasons)


class KataGo:
    def __init__(self):
        self.binary=os.getenv('KATAGO_BINARY','')
        self.model=os.getenv('KATAGO_MODEL','')
        self.timeout=float(os.getenv('KATAGO_TIMEOUT','60'))
        self.gate=asyncio.Semaphore(1)

    @property
    def configured(self):
        return bool(self.binary and self.model)

    async def analyze(self,room):
        if not self.configured:
            raise RuntimeError('KataGo engine/model is not configured')
        requests=[query(room,'quick',256),query(room,'deep',1024)]
        results = await self.run(requests)
        return adjudicate(room.board,room.captures,results['quick'],results['deep'])

    async def run(self, requests):
        async with asyncio.timeout(self.timeout):
            async with self.gate:
                process=await asyncio.create_subprocess_exec(self.binary,'analysis','-model',self.model,'-config',str(ROOT/'katago.cfg'),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=2**20)
                try:
                    process.stdin.write(('\n'.join(json.dumps(q) for q in requests)+'\n').encode())
                    await process.stdin.drain()
                    results={}
                    while len(results)<2:
                        line=await process.stdout.readline()
                        if not line:
                            raise RuntimeError('KataGo stopped before completing analysis')
                        data=json.loads(line)
                        if data.get('id') in ('quick','deep') and not data.get('isDuringSearch'):
                            if data.get('error'):
                                raise ValueError('KataGo rejected position')
                            requested = next(q['maxVisits'] for q in requests if q['id'] == data['id'])
                            if data.get('rootInfo', {}).get('visits', 0) < requested:
                                raise ValueError('Engine search did not reach the requested budget')
                            results[data['id']]=data
                    return results
                finally:
                    if process.returncode is None:
                        try: process.kill()
                        except ProcessLookupError: pass
                    await process.wait()
