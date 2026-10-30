"""Optional KataGo preview opponent. Strength requires empirical calibration."""
import asyncio
import json
import os
import re
from pathlib import Path
from adjudicator import coordinate, settled_adjudication

class ResidentEngine:
    """One serialized process; discard it on cancellation or protocol failure."""
    def __init__(self):
        self.gate = asyncio.Lock()
        self.process = None
        self.config = None
        self.serial = 0

    async def close(self):
        process, self.process = self.process, None
        self.config = None
        if process is not None:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()

    async def query(self, binary, model, query):
        # Waiting callers must not kill the process owned by another search.
        async with asyncio.timeout(15):
            async with self.gate:
                try:
                    config = (binary, model)
                    if (self.process is None or self.process.returncode is not None
                            or self.config != config):
                        await self.close()
                        self.process = await asyncio.create_subprocess_exec(
                            binary, 'analysis', '-model', model, '-config',
                            str(Path(__file__).with_name('katago.cfg')),
                            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.DEVNULL, limit=2**20)
                        self.config = config
                    self.serial += 1
                    query = dict(query, id=f'preview-{self.serial}')
                    self.process.stdin.write((json.dumps(query)+'\n').encode())
                    await self.process.stdin.drain()
                    while True:
                        line = await self.process.stdout.readline()
                        if not line:
                            raise RuntimeError('Engine stopped')
                        result = json.loads(line)
                        if not isinstance(result, dict):
                            raise ValueError('Invalid engine response object')
                        if result.get('id') == query['id'] and not result.get('isDuringSearch'):
                            return result
                except BaseException:
                    await self.close()
                    raise


_ENGINE = ResidentEngine()


async def shutdown():
    await _ENGINE.close()


def settings():
    if os.getenv('GO13_STRONG_BOT', '').lower() == 'false':
        return None, None
    binary, model = os.getenv('GO13_BOT_BINARY'), os.getenv('GO13_BOT_MODEL')
    if not binary and not model and os.getenv('GO13_PREVIEW', '').lower() == 'true':
        root = Path('/opt/go13-ai')
        if (root / 'squashfs-root/AppRun').is_file() and (root / 'model.txt.gz').is_file():
            return str(root / 'squashfs-root/AppRun'), str(root / 'model.txt.gz')
    return binary, model


def configured():
    return all(settings())


def move_history(state):
    moves = re.findall(r';([BW])\[([a-m]{2}|)\]', state['sgf'])
    if len(moves) != state['moves']:
        raise ValueError('Incomplete game history')
    return [[color, coordinate((ord(pos[1])-97)*13+ord(pos[0])-97) if pos else 'pass']
            for color, pos in moves]


def select_action(result, state, try_move, board_hash, ko_position=None):
    if result.get('error') or result.get('warnings') or result.get('warning'):
        raise ValueError('Engine rejected requested position/rules')
    candidates = result.get('moveInfos')
    if not isinstance(candidates, list) or not candidates:
        raise ValueError('No engine moves')
    forbidden = {ko_position} if ko_position else set()
    # Validate on the same server rules; never trust an engine coordinate alone.
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        move = candidate.get('move', '')
        if not isinstance(move, str):
            continue
        if move.lower() == 'pass':
            if settled_adjudication(state['board'], state['captures']):
                return {'type': 'pass'}
            continue
        match = re.fullmatch(r'([A-HJ-N])(1[0-3]|[1-9])', move)
        if not match:
            continue
        index = (13-int(match[2]))*13+'ABCDEFGHJKLMN'.index(match[1])
        try:
            try_move(state['board'], index, -1, forbidden)
        except ValueError:
            continue
        return {'type': 'move', 'index': index}
    raise ValueError('No legal non-pass engine move in unfinished position')


async def choose_action(state, try_move, board_hash, ko_position=None):
    # Distinct variables keep move generation independent of scoring configuration.
    binary, model = settings()
    if not binary or not model:
        raise RuntimeError('Strong preview opponent is not configured')
    visits = max(16, min(256, int(os.getenv('GO13_BOT_VISITS', '16'))))
    query = dict(id='preview-move', moves=move_history(state), rules='japanese', komi=6.5,
                 boardXSize=13, boardYSize=13, maxVisits=visits, analysisPVLen=1)
    result = await _ENGINE.query(binary, model, query)
    return select_action(result, state, try_move, board_hash, ko_position)
