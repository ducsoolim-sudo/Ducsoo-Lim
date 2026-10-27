"""Preview-only opponent using the same public WebSocket protocol as a player."""
import asyncio
import json
import random
from aiohttp import ClientSession, WSMsgType


def choose_action(state, try_move, board_hash):
    if state['passes']:
        return {'type': 'pass'}
    choices=[]
    for index,stone in enumerate(state['board']):
        if stone:continue
        try:
            _,captured=try_move(state['board'],index,-1,set())
        except ValueError:
            continue
        x,y=index%13,index//13
        edge=min(x,y,12-x,12-y)
        # A lightweight test opponent, not an AI strength/rating claim.
        choices.append((captured*100 + min(edge,3)*2 + random.random()*8,index))
    return {'type':'move','index':max(choices)[1]} if choices else {'type':'pass'}


async def run_bot(port, code, ready, try_move, board_hash):
    try:
        async with asyncio.timeout(1200):
            async with ClientSession() as session:
                async with session.ws_connect(f'http://127.0.0.1:{port}/ws') as socket:
                    await socket.send_json({'type':'join','room':code,'name':'Test Bot'})
                    last_action=None
                    completed=False
                    while True:
                        event=await socket.receive(timeout=120 if completed else None)
                        if event.type!=WSMsgType.TEXT:break
                        message=json.loads(event.data)
                        if message['type']=='welcome':
                            if message['role']!='white':raise RuntimeError('Bot seat unavailable')
                            if not ready.done():ready.set_result(True)
                        if message['type']=='error':
                            # A rejected ko candidate is recovered safely by a pass.
                            if 'Ko:' in message.get('message',''):
                                await socket.send_json({'type':'pass'})
                            continue
                        if message['type']!='state':continue
                        state=message['state']
                        completed=state['status']=='finished'
                        marker=(state['gameId'],state['moves'],state['status'],tuple(state['rematch']),tuple(state['dead']),tuple(state['approvals']),str(state.get('adjudication',{})))
                        if marker==last_action:continue
                        if state['status']=='cancelled':break
                        if state['status']=='finished' and 'black' in state['rematch'] and 'white' not in state['rematch']:
                            last_action=marker;await socket.send_json({'type':'rematch'})
                        elif state['status']=='scoring' and state.get('adjudication',{}):
                            if state['adjudication'].get('status')=='ready' and 'white' not in state['approvals']:
                                last_action=marker;await socket.send_json({'type':'approve'})
                        elif state['status']=='scoring' and not state.get('scoreUncertain') and 'white' not in state['approvals']:
                            last_action=marker;await socket.send_json({'type':'approve'})
                        elif state['status']=='playing' and state['turn']=='white':
                            last_action=marker
                            await asyncio.sleep(.65)
                            await socket.send_json(choose_action(state,try_move,board_hash))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if not ready.done():ready.set_exception(exc)
