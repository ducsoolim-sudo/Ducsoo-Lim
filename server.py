"""13GO: small real-time 13x13 Go server. Run: python server.py"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import string
import time
from collections import deque
from pathlib import Path

from aiohttp import web, WSMsgType

N = 13
KOMI = 6.5
ROOT = Path(__file__).resolve().parent
ROOMS: dict[str, "Room"] = {}
# The first deployment uses a single aiohttp worker. Multiple workers require a
# shared room store and distributed message delivery; see README.md.
MAX_ROOMS = int(os.environ.get("MAX_ROOMS", "2000"))
MAX_CLIENTS = int(os.environ.get("MAX_CLIENTS", "2500"))
MAX_SPECTATORS_PER_ROOM = int(os.environ.get("MAX_SPECTATORS_PER_ROOM", "100"))
RATE_WINDOW = 60
RATE_LIMIT = int(os.environ.get("CREATE_RATE_LIMIT", "2400"))
REQUEST_TIMES: dict[str, deque[float]] = {}
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def neighbors(pos: int):
    x, y = pos % N, pos // N
    if x > 0:
        yield pos - 1
    if x < N - 1:
        yield pos + 1
    if y > 0:
        yield pos - N
    if y < N - 1:
        yield pos + N


def group_and_liberties(board: list[int], start: int) -> tuple[set[int], set[int]]:
    color = board[start]
    if not color:
        return set(), set()
    group, liberties = {start}, set()
    todo = [start]
    while todo:
        at = todo.pop()
        for nxt in neighbors(at):
            if board[nxt] == 0:
                liberties.add(nxt)
            elif board[nxt] == color and nxt not in group:
                group.add(nxt)
                todo.append(nxt)
    return group, liberties


def board_hash(board: list[int]) -> str:
    return "".join(str(x) for x in board)


def try_move(board: list[int], index: int, color: int, seen: set[str]) -> tuple[list[int], int]:
    if index < 0 or index >= N * N or board[index] != 0:
        raise ValueError("This point is occupied or outside the board.")
    result = board.copy()
    result[index] = color
    taken: set[int] = set()
    for near in neighbors(index):
        if result[near] == -color:
            stones, libs = group_and_liberties(result, near)
            if not libs:
                taken.update(stones)
    for stone in taken:
        result[stone] = 0
    _, own_libs = group_and_liberties(result, index)
    if not own_libs:
        raise ValueError("Suicide moves are not allowed.")
    if board_hash(result) in seen:
        raise ValueError("Ko: a previous board position cannot be repeated.")
    return result, len(taken)


def area_score(board: list[int], dead: set[int]) -> dict:
    """Chinese-style area scoring after jointly agreed dead-group marking."""
    alive = [0 if i in dead else c for i, c in enumerate(board)]
    stones = {1: alive.count(1), -1: alive.count(-1)}
    territory = {1: 0, -1: 0}
    visited: set[int] = set()
    neutral = 0
    for i, c in enumerate(alive):
        if c != 0 or i in visited:
            continue
        region: set[int] = {i}
        borders: set[int] = set()
        todo = [i]
        visited.add(i)
        while todo:
            at = todo.pop()
            for nxt in neighbors(at):
                if alive[nxt] == 0 and nxt not in visited:
                    visited.add(nxt)
                    region.add(nxt)
                    todo.append(nxt)
                elif alive[nxt] != 0:
                    borders.add(alive[nxt])
        if len(borders) == 1:
            territory[next(iter(borders))] += len(region)
        else:
            neutral += len(region)
    black = stones[1] + territory[1]
    white = stones[-1] + territory[-1] + KOMI
    return {
        "black": black, "white": white, "komi": KOMI,
        "blackStones": stones[1], "whiteStones": stones[-1],
        "blackTerritory": territory[1], "whiteTerritory": territory[-1],
        "neutral": neutral,
        "winner": "black" if black > white else "white",
        "margin": round(abs(black - white), 1),
    }


class Room:
    def __init__(self, code: str, public: bool = False, solo: bool = False):
        self.game_id = secrets.token_urlsafe(12)
        self.code = code
        self.public = public and not solo
        self.solo = solo
        self.board = [0] * (N * N)
        self.history: set[str] = {board_hash(self.board)}
        self.turn = 1
        self.status = "waiting"
        self.players: dict[str, dict | None] = {"black": None, "white": None}
        self.clients: dict[web.WebSocketResponse, str] = {}
        self.captures = {"black": 0, "white": 0}
        self.passes = 0
        self.moves = 0
        self.move_record: list[tuple[int, int | None]] = []
        self.last_move: int | None = None
        self.dead: set[int] = set()
        self.approvals: set[str] = set()
        self.rematch: set[str] = set()
        self.result: dict | None = None
        self.modified = time.monotonic()

    def claim(self, token: str | None, name: str) -> tuple[str, str | None]:
        self.modified = time.monotonic()
        for role in ("black", "white"):
            player = self.players[role]
            if player and token and secrets.compare_digest(player["token"], token):
                return role, player["token"]
        if self.solo and self.players["black"]:
            return "spectator", None
        for role in ("black", "white"):
            if self.players[role] is None:
                token = secrets.token_urlsafe(24)
                self.players[role] = {"token": token, "name": name[:16] or ("Black" if role == "black" else "White")}
                if self.solo:
                    self.players["white"] = {"token": secrets.token_urlsafe(24), "name": name[:16] + " · White"}
                if self.players["black"] and self.players["white"] and self.status == "waiting":
                    self.status = "playing"
                return role, token
        return "spectator", None

    def connected(self, role: str) -> bool:
        return any(r == role and not ws.closed for ws, r in self.clients.items())

    def state(self) -> dict:
        return {
            "room": self.code,
            "gameId": self.game_id,
            "solo": self.solo,
            "spectators": sum(role == "spectator" for role in self.clients.values()),
            "board": self.board,
            "turn": "black" if self.turn == 1 else "white",
            "status": self.status,
            "players": {role: ({"name": self.players[role]["name"], "connected": self.connected(role)}
                              if self.players[role] else None) for role in ("black", "white")},
            "captures": self.captures,
            "passes": self.passes,
            "moves": self.moves,
            "sgf": self.sgf(),
            "lastMove": self.last_move,
            "dead": sorted(self.dead),
            "approvals": sorted(self.approvals),
            "rematch": sorted(self.rematch),
            "score": area_score(self.board, self.dead) if self.status == "scoring" else None,
            "result": self.result,
        }

    def sgf(self) -> str:
        def escape(value):
            return str(value).replace("\\", "\\\\").replace("]", "\\]").replace("\r", " ").replace("\n", " ")
        headers = "(;GM[1]FF[4]CA[UTF-8]AP[13GO]SZ[13]KM[6.5]RU[Chinese]"
        for role, prop in (("black", "PB"), ("white", "PW")):
            headers += prop + "[" + escape((self.players[role] or {}).get("name", role)) + "]"
        if self.result:
            winner = "B" if self.result["winner"] == "black" else "W"
            margin = "R" if self.result["reason"] == "resign" else str(self.result["margin"])
            headers += "RE[" + winner + "+" + margin + "]"
        for color, index in self.move_record:
            point = "" if index is None else chr(97 + index % N) + chr(97 + index // N)
            headers += ";" + ("B" if color == 1 else "W") + "[" + point + "]"
        return headers + ")"

    async def broadcast(self):
        self.modified = time.monotonic()
        data = {"type": "state", "state": self.state()}
        for client in tuple(self.clients):
            if client.closed:
                self.clients.pop(client, None)
                continue
            try:
                await client.send_json(data)
            except (ConnectionResetError, RuntimeError):
                self.clients.pop(client, None)

    def act(self, role: str, action: dict):
        if role not in ("black", "white"):
            raise ValueError("Spectators cannot play moves.")
        if self.solo:
            if role != "black":
                raise ValueError("Only the solo player can control this game.")
            role = "black" if self.turn == 1 else "white"
        kind = action.get("type")
        if kind in ("move", "pass"):
            if self.status != "playing":
                raise ValueError("Moves are only allowed during play.")
            expected = "black" if self.turn == 1 else "white"
            if role != expected:
                raise ValueError("It is your opponent's turn.")
            if kind == "move":
                index = action.get("index")
                if type(index) is not int:
                    raise ValueError("Invalid move position.")
                self.board, captured = try_move(self.board, index, self.turn, self.history)
                self.history.add(board_hash(self.board))
                self.captures[role] += captured
                self.last_move = index
                self.passes = 0
            else:
                self.passes += 1
                self.last_move = None
            self.move_record.append((self.turn, index if kind == "move" else None))
            self.moves += 1
            self.turn *= -1
            if self.passes == 2:
                self.status = "scoring"
                self.dead.clear()
                self.approvals.clear()
        elif kind == "dead":
            if self.status != "scoring":
                raise ValueError("Dead stones can only be marked during scoring.")
            index = action.get("index")
            if type(index) is not int or not 0 <= index < N * N or not self.board[index]:
                raise ValueError("Select a stone to mark its group as dead.")
            group, _ = group_and_liberties(self.board, index)
            if group.issubset(self.dead):
                self.dead.difference_update(group)
            else:
                self.dead.update(group)
            self.approvals.clear()
        elif kind == "approve":
            if self.status != "scoring":
                raise ValueError("The score can only be accepted during scoring.")
            self.approvals.update(("black", "white") if self.solo else (role,))
            if len(self.approvals) == 2:
                self.result = {"reason": "score", **area_score(self.board, self.dead)}
                self.status = "finished"
        elif kind == "resume":
            if self.status != "scoring":
                raise ValueError("This game cannot be resumed right now.")
            self.status = "playing"
            self.passes = 0
            self.dead.clear()
            self.approvals.clear()
        elif kind == "resign":
            if self.status not in ("playing", "scoring"):
                raise ValueError("You can only resign an active game.")
            self.result = {"reason": "resign", "winner": "white" if role == "black" else "black"}
            self.status = "finished"
        elif kind == "rematch":
            if self.status != "finished":
                raise ValueError("A rematch is available after the game ends.")
            self.rematch.update(("black", "white") if self.solo else (role,))
            if len(self.rematch) == 2:
                self.game_id = secrets.token_urlsafe(12)
                self.board = [0] * (N * N)
                self.history = {board_hash(self.board)}
                self.turn = 1
                self.status = "playing"
                self.captures = {"black": 0, "white": 0}
                self.passes = 0
                self.moves = 0
                self.move_record.clear()
                self.last_move = None
                self.dead.clear()
                self.approvals.clear()
                self.rematch.clear()
                self.result = None
        else:
            raise ValueError("Unknown action.")


def new_room(public: bool = False, solo: bool = False) -> Room:
    if len(ROOMS) >= MAX_ROOMS:
        raise web.HTTPServiceUnavailable(text="The server is busy. Please try again shortly.")
    code = "".join(secrets.choice(ALPHABET) for _ in range(7))
    while code in ROOMS:
        code = "".join(secrets.choice(ALPHABET) for _ in range(7))
    room = Room(code, public=public, solo=solo)
    ROOMS[code] = room
    return room


def request_name(data: dict) -> str:
    name = data.get("name", "Player")
    if not isinstance(name, str):
        name = "Player"
    name = " ".join(name.strip().split())[:16]
    return name or "Player"


async def input_json(request) -> dict:
    try:
        data = await request.json()
    except (ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def check_rate(request):
    # Do not trust X-Forwarded-For from untrusted clients.
    ip = request.remote or "unknown"
    now = time.monotonic()
    timestamps = REQUEST_TIMES.setdefault(ip, deque())
    while timestamps and now - timestamps[0] > RATE_WINDOW:
        timestamps.popleft()
    if len(timestamps) >= RATE_LIMIT:
        raise web.HTTPTooManyRequests(text="Too many game requests. Please wait a moment.")
    timestamps.append(now)


def lobby_snapshot():
    public = [room for room in ROOMS.values() if room.public]
    waiting = [r for r in public if r.status == "waiting" and
               (r.connected("black") or time.monotonic() - r.modified < 30)]
    playing = [r for r in public if r.status in ("playing", "scoring")]
    # Only active connections count as being online, not reserved seats.
    online = sum(len(room.clients) for room in ROOMS.values())
    visible = sorted(waiting, key=lambda r: -r.modified) + sorted(playing, key=lambda r: -r.modified)
    return {
        "online": online,
        "rooms": len(ROOMS),
        "playing": len(playing),
        "waiting": len(waiting),
        "list": [{
            "room": r.code,
            "status": r.status,
            "black": r.players["black"]["name"] if r.players["black"] else None,
            "white": r.players["white"]["name"] if r.players["white"] else None,
            "spectators": sum(role == "spectator" for role in r.clients.values()),
            "moves": r.moves,
        } for r in visible[:32]],
    }


async def index(request):
    return web.FileResponse(ROOT / "static" / "index.html")


async def health(request):
    return web.json_response({"ok": True, "version": "1.0.0", "rooms": len(ROOMS)})


async def lobby(request):
    return web.json_response(lobby_snapshot())


async def create_room(request):
    check_rate(request)
    data = await input_json(request)
    room = new_room(public=bool(data.get("public", False)), solo=data.get("solo") is True)
    role, token = room.claim(None, request_name(data))
    assert role == "black"
    return web.json_response({"room": room.code, "token": token, "role": role})


async def match_room(request):
    """Match any newcomer into a publicly visible waiting room.

    Seat reservation and room selection are synchronous within one event loop,
    so concurrent HTTP requests cannot claim the same color.
    """
    check_rate(request)
    data = await input_json(request)
    now = time.monotonic()
    candidates = [r for r in ROOMS.values()
                  if r.public and r.status == "waiting"
                  and r.players["black"] is not None
                  and r.players["white"] is None
                  and (r.connected("black") or now - r.modified < 30)]
    if candidates:
        # Prefer an opponent who is actively connected.
        room = min(candidates, key=lambda r: (not r.connected("black"), r.modified))
    else:
        room = new_room(public=True)
    role, token = room.claim(None, request_name(data))
    return web.json_response({"room": room.code, "token": token,
                              "role": role, "matched": role == "white"})


async def websocket_handler(request):
    socket = web.WebSocketResponse(heartbeat=25, max_msg_size=2048)
    client_count = sum(len(r.clients) for r in ROOMS.values())
    if client_count >= MAX_CLIENTS:
        raise web.HTTPServiceUnavailable(text="The connection limit has been reached.")
    await socket.prepare(request)
    room: Room | None = None
    role = "spectator"
    last_messages = deque()
    try:
        async for event in socket:
            if event.type != WSMsgType.TEXT:
                continue
            now = time.monotonic()
            while last_messages and now - last_messages[0] > 5:
                last_messages.popleft()
            if len(last_messages) >= 30:
                await socket.close(code=1008, message=b"rate limit")
                break
            last_messages.append(now)
            try:
                data = json.loads(event.data)
                if not isinstance(data, dict):
                    raise ValueError("Invalid message.")
                if room is None:
                    if data.get("type") != "join":
                        raise ValueError("Join a game first.")
                    code = str(data.get("room", "")).upper()
                    room = ROOMS.get(code)
                    if not room:
                        raise ValueError("Game not found. Please start a new game.")
                    token = data.get("token") if isinstance(data.get("token"), str) else None
                    name = data.get("name", "Player")
                    if not isinstance(name, str):
                        name = "Player"
                    if data.get("mode") == "watch":
                        role, token = "spectator", None
                    else:
                        role, token = room.claim(token, name)
                    if role == "spectator" and sum(
                        r == "spectator" for r in room.clients.values()
                    ) >= MAX_SPECTATORS_PER_ROOM:
                        raise ValueError("This game has reached its spectator limit.")
                    room.clients[socket] = role
                    await socket.send_json({"type": "welcome", "role": role, "token": token, "room": code})
                    await room.broadcast()
                else:
                    room.act(role, data)
                    await room.broadcast()
            except (ValueError, json.JSONDecodeError) as exc:
                await socket.send_json({"type": "error", "message": str(exc)})
    finally:
        if room:
            room.clients.pop(socket, None)
            await room.broadcast()
    return socket


async def cleanup_loop(app):
    try:
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            for code, room in list(ROOMS.items()):
                stale_seconds = 600 if room.status == "waiting" else 86400
                if not room.clients and now - room.modified > stale_seconds:
                    ROOMS.pop(code, None)
    except asyncio.CancelledError:
        pass


async def cleanup_context(app):
    task = asyncio.create_task(cleanup_loop(app))
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def make_app():
    app = web.Application(client_max_size=2048)
    app.router.add_get("/", index)
    app.router.add_post("/api/rooms", create_room)
    app.router.add_post("/api/match", match_room)
    app.router.add_get("/api/lobby", lobby)
    app.router.add_get("/health", health)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/static/", ROOT / "static", show_index=False)
    app.cleanup_ctx.append(cleanup_context)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"13GO: http://localhost:{port}")
    web.run_app(make_app(), host="0.0.0.0", port=port)

