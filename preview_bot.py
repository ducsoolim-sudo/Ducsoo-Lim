"""Preview-only opponent using the same public WebSocket protocol as a player."""
import asyncio
import json
import random
import logging
import strong_bot
from aiohttp import ClientSession, WSMsgType


def choose_action(state, try_move, board_hash, ko_position=None):
    """Bounded two-ply tactical opponent; no rank/strength certification."""
    from scoring import adjacent, group
    from adjudicator import settled_adjudication
    board = state['board']
    if state['passes'] and settled_adjudication(board, state.get('captures', {'black': 0, 'white': 0})):
        return {'type': 'pass'}
    forbidden = {ko_position} if ko_position else set()

    def groups(position, color):
        seen = set()
        result = []
        for point, stone in enumerate(position):
            if stone == color and point not in seen:
                stones, liberties = group(position, point)
                seen.update(stones)
                result.append((stones, liberties))
        return result

    own = groups(board, -1)
    enemy = groups(board, 1)
    urgent = {next(iter(libs)) for stones, libs in own if len(libs) == 1}
    choices = []
    for index, stone in enumerate(board):
        if stone:
            continue
        try:
            position, captured = try_move(board, index, -1, forbidden)
        except ValueError:
            continue
        stones, liberties = group(position, index)
        x, y = index % 13, index // 13
        edge = min(x, y, 12-x, 12-y)
        # Third/fourth-line development, rather than a random central pile.
        score = (9 if edge in (2, 3) else 4 if edge > 3 else -5 if edge == 1 else -12)
        if own:
            distance = min(abs(x-p%13)+abs(y-p//13) for g, _ in own for p in g)
            score += 10 if distance in (3, 4) else 5 if distance == 2 else 0
        score += captured * 110
        score += sum(len(g)*95 for g, libs in own if len(libs) == 1 and index in libs and len(liberties) > 1)
        score -= 140*len(stones) if len(liberties) == 1 else 0
        score += min(len(liberties), 6)*2
        score += sum(min(len(g), 5)*12 for g, libs in enemy if len(libs) == 2 and index in libs)
        touching = [g for g, _ in own if any(n in g for n in adjacent(index))]
        if len(touching) > 1:
            score += 15*(len(touching)-1)
        # Preserve eyes, but still allow a necessary capture or tactical defense.
        if not captured and all(board[n] == -1 for n in adjacent(index)):
            score -= 100
        choices.append((score + random.random()*.2, index, position, captured))
    if not choices:
        return {'type': 'pass'}
    choices.sort(reverse=True)
    # Read the opponent's immediate captures/atari around weak groups.
    candidates = choices[:10]
    candidates += [c for c in choices[10:] if c[1] in urgent]
    ranked = []
    for score, index, position, captured in candidates:
        reply_points = set()
        for stones, liberties in groups(position, -1):
            if len(liberties) <= 2:
                reply_points.update(liberties)
        punishment = 0
        for reply in reply_points:
            try:
                after, taken = try_move(position, reply, 1, {board_hash(board)})
            except ValueError:
                continue
            threat = sum(len(g)*18 for g, libs in groups(after, -1) if len(libs) == 1)
            punishment = max(punishment, taken*155 + threat)
        ranked.append((score-punishment, index))
    return {'type': 'move', 'index': max(ranked)[1]}


async def run_bot(port, code, ready, try_move, board_hash):
    try:
        async with asyncio.timeout(1200):
            async with ClientSession() as session:
                async with session.ws_connect(f'http://127.0.0.1:{port}/ws') as socket:
                    await socket.send_json({'type':'join','room':code,'name':'Test Bot'})
                    last_action=None
                    completed=False
                    last_board=None
                    previous_position=None
                    pending_action=None
                    pending_retries=0

                    async def send_action(action):
                        nonlocal pending_action,pending_retries
                        pending_action=action.copy()
                        pending_retries=0
                        await socket.send_json(action)

                    while True:
                        event=await socket.receive(timeout=120 if completed else None)
                        if event.type!=WSMsgType.TEXT:break
                        message=json.loads(event.data)
                        if message['type']=='welcome':
                            if message['role']!='white':raise RuntimeError('Bot seat unavailable')
                            if not ready.done():ready.set_result(True)
                        if message['type']=='error':
                            # A failed durable save rolled the action back. Retry that
                            # same command briefly; never invent a replacement move.
                            if (message.get('message')=='Move not saved. Please try again.'
                                    and pending_action is not None and pending_retries<2):
                                pending_retries+=1
                                await asyncio.sleep(2**(pending_retries-1))
                                await socket.send_json(pending_action)
                            # A rejected ko candidate is recovered safely by a pass.
                            if 'Ko:' in message.get('message',''):
                                await socket.send_json({'type':'pass'})
                            continue
                        if message['type']!='state':continue
                        state=message['state']
                        if last_board is not None and last_board != state['board']:
                            previous_position=board_hash(last_board)
                        last_board=state['board'].copy()
                        completed=state['status']=='finished'
                        recovering=bool((state.get('clock') or {}).get('recovering'))
                        marker=(state['gameId'],state['moves'],state['status'],tuple(state['rematch']),tuple(state['dead']),tuple(state['approvals']),str(state.get('adjudication',{})),recovering)
                        if recovering:
                            # Recovery can end without a new move. Do not let a
                            # rejected pre-pause command suppress that same turn.
                            last_action=None
                            pending_action=None
                            continue
                        if marker==last_action:continue
                        pending_action=None
                        if state['status']=='cancelled':break
                        if state['status']=='finished' and 'black' in state['rematch'] and 'white' not in state['rematch']:
                            last_action=marker;await send_action({'type':'rematch'})
                        elif state['status']=='scoring' and state.get('adjudication',{}):
                            if state['adjudication'].get('status')=='ready' and 'white' not in state['approvals']:
                                last_action=marker;await send_action({'type':'approve'})
                        elif state['status']=='scoring' and not state.get('scoreUncertain') and 'white' not in state['approvals']:
                            last_action=marker;await send_action({'type':'approve'})
                        elif state['status']=='playing' and state['turn']=='white':
                            last_action=marker
                            await asyncio.sleep(.65)
                            if strong_bot.configured():
                                try:
                                    action=await strong_bot.choose_action(state,try_move,board_hash,previous_position)
                                except (ValueError, RuntimeError, OSError, TimeoutError):
                                    # Explicit test helper only: preserve availability, never advertise a rank.
                                    logging.warning('Strong test opponent unavailable; using unrated tactical fallback')
                                    action=await asyncio.to_thread(choose_action,state,try_move,board_hash,previous_position)
                            else:
                                action=await asyncio.to_thread(choose_action,state,try_move,board_hash,previous_position)
                            await send_action(action)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if not ready.done():ready.set_exception(exc)
