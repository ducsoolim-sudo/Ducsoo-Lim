"""Real-engine smoke/regression check. Set KATAGO_BINARY and KATAGO_MODEL."""
import asyncio
import argparse
import json
import os
import time
from pathlib import Path
from adjudicator import KataGo, adjudicate, coordinate


def fixtures():
    # Fixed setup positions: no invented move order or ko history.
    dead=[1]*169
    for p in (0,2,85):dead[p]=0
    dead[84]=-1
    # Two groups sharing two liberties, each with one private eye.
    seki=[1 if p%13<6 else -1 for p in range(169)]
    for p in (0,12,6*13+5,7*13+6):seki[p]=0
    # Early double pass is deliberately unsettled and must not auto-confirm.
    open_board=[0]*169;open_board[0]=1;open_board[14]=-1
    return [('enclosed-death',dead),('shared-liberties',seki),('unfinished',open_board)]


async def main(args):
    engine=KataGo()
    if not engine.configured:raise SystemExit('Set KATAGO_BINARY and KATAGO_MODEL')
    reports=[]
    for name,board in fixtures():
        if args.case and name not in args.case:
            continue
        started=time.monotonic()
        setup=[['B' if c==1 else 'W',coordinate(i)] for i,c in enumerate(board) if c]
        requests=[dict(id=ident,initialStones=setup,initialPlayer='B',moves=[],rules='japanese',komi=6.5,boardXSize=13,boardYSize=13,includeOwnership=True,includeOwnershipStdev=True,maxVisits=visits) for ident,visits in [('quick',args.visits[0]),('deep',args.visits[1])]]
        results=await engine.run(requests)
        verdict=adjudicate(board,{'black':0,'white':0},results['quick'],results['deep'])
        checks = {
            'enclosed-death': verdict['dead']==[84] and verdict['status']=='ready',
            'shared-liberties': not verdict['dead'] and verdict['status']=='ready' and verdict['score']['blackTerritory']==0 and verdict['score']['whiteTerritory']==0,
            'unfinished': verdict['status']=='review',
        }
        reports.append(dict(fixture=name,passed=checks[name],visits=args.visits,status=verdict['status'],dead=verdict['dead'],uncertain=len(verdict['uncertain']),margin=verdict['score']['margin'],reasons=verdict['reasons'],seconds=round(time.monotonic()-started,2),leads=[results[k]['rootInfo']['scoreLead'] for k in ('quick','deep')]))
        print(json.dumps(reports[-1]),flush=True)
        if os.getenv('KATAGO_REPORT'):
            Path(os.environ['KATAGO_REPORT']).write_text(json.dumps(reports,indent=2)+'\n')
    if os.getenv('KATAGO_REPORT'):
        Path(os.environ['KATAGO_REPORT']).write_text(json.dumps(reports,indent=2)+'\n')
    return reports


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--visits',nargs=2,type=int,default=[256,1024])
    parser.add_argument('--case',action='append',choices=[name for name,_ in fixtures()])
    args=parser.parse_args()
    if min(args.visits)<1 or args.visits[0]>=args.visits[1]:parser.error('Visits must be positive and increasing')
    reports=asyncio.run(main(args))
    raise SystemExit(0 if all(r['passed'] for r in reports) else 1)
