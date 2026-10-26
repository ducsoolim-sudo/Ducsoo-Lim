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
from storage import RoomStore, StaleRoom
import copy
import logging

N = 13
KOMI = 6.5
VERSION = "1.1.0"
MAIN_SECONDS = 300.0
INCREMENT = 3.0
DISCONNECT_GRACE = 90.0
REVIEW_SECONDS = 120.0
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
        self.revision = 0
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
        self.modified = time.time()
        self.created = time.time()
        self.remaining = {"black": MAIN_SECONDS, "white": MAIN_SECONDS}
        self.turn_started = None
        self.review_deadline = None
        self.absent_since = {"black": None, "white": None}

    def snapshot(self):
        data = copy.deepcopy({k: v for k, v in self.__dict__.items() if k != "clients"})
        for key in ("history", "dead", "approvals", "rematch"):
            data[key] = list(data[key])
        return data

    def restore(self, data):
        for key, value in copy.deepcopy(data).items():
            if key != "clients":
                setattr(self, key, value)
        for key in ("history", "dead", "approvals", "rematch"):
            setattr(self, key, set(getattr(self, key)))

    @classmethod
    def from_snapshot(cls, data):
        room = cls(data["code"])
        room.restore(data)
        return room

    def clock(self, now=None):
        now = time.time() if now is None else now
        remaining = self.remaining.copy()
        role = "black" if self.turn == 1 else "white"
        if self.status == "playing" and self.turn_started is not None:
            remaining[role] = max(0.0, remaining[role] - max(0.0, now - self.turn_started))
        return {"remaining": remaining, "running": role if self.status == "playing" and self.turn_started is not None else None,
                "increment": INCREMENT, "serverTime": now, "reviewDeadline": self.review_deadline}

    def tick(self, now=None):
        now = time.time() if now is None else now
        if self.solo or self.status not in ("playing", "scoring"):
            return False
        if self.status == "playing" and self.turn_started is not None:
            role = "black" if self.turn == 1 else "white"
            if self.clock(now)["remaining"][role] <= 0:
                self.remaining[role] = 0
                self.result = {"reason": "time", "winner": "white" if role == "black" else "black"}
                self.status = "finished"
                self.turn_started = None
                return True
        if self.status == "scoring" and self.review_deadline and now >= self.review_deadline:
            if len(self.approvals) == 1:
                self.result = {"reason": "review_timeout", "winner": next(iter(self.approvals))}
                self.status = "finished"
            else:
                self.status = "cancelled"
            return True
        for role in ("black", "white"):
            other = "white" if role == "black" else "black"
            absent = self.absent_since[role]
            if absent is not None and now - absent >= DISCONNECT_GRACE and self.connected(other):
                if self.turn_started is None and self.moves == 0:
                    self.status = "cancelled"
                else:
                    self.result = {"reason": "disconnect", "winner": other}
                    self.status = "finished"
                    self.turn_started = None
                return True
        return False

    def connection_changed(self):
        now = time.time()
        if self.solo:
            return
        for role in ("black", "white"):
            if self.connected(role):
                self.absent_since[role] = None
            elif self.players[role] and self.absent_since[role] is None:
                self.absent_since[role] = now
        if self.status == "playing" and self.turn_started is None and self.moves == 0 and all(self.connected(r) for r in ("black", "white")):
            self.turn_started = now

    def claim(self, token: str | None, name: str) -> tuple[str, str | None]:
        self.modified = time.time()
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
            "queueSince": self.created,
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
            "clock": None if self.solo else self.clock(),
            "disconnectGrace": DISCONNECT_GRACE,
            "absentSince": self.absent_since,
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
            margin = str(self.result["margin"]) if self.result["reason"] == "score" else "T" if self.result["reason"] == "time" else "R"
            headers += "RE[" + winner + "+" + margin + "]"
        for color, index in self.move_record:
            point = "" if index is None else chr(97 + index % N) + chr(97 + index // N)
            headers += ";" + ("B" if color == 1 else "W") + "[" + point + "]"
        return headers + ")"

    async def broadcast(self):
        self.modified = time.time()
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
        now = time.time()
        if self.tick(now):
            return
        if kind == "cancel":
            if self.status != "waiting":
                raise ValueError("An opponent has already joined. Please continue the game.")
            self.status = "cancelled"
            return
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
            if not self.solo:
                self.remaining[role] = self.clock(now)["remaining"][role] + INCREMENT
                self.turn_started = now
            self.move_record.append((self.turn, index if kind == "move" else None))
            self.moves += 1
            self.turn *= -1
            if self.passes == 2:
                self.status = "scoring"
                self.turn_started = None
                self.review_deadline = None if self.solo else now + REVIEW_SECONDS
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
            self.turn_started = None if self.solo else now
            self.review_deadline = None
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
                self.remaining = {"black": MAIN_SECONDS, "white": MAIN_SECONDS}
                self.turn_started = None if self.solo else now
                self.review_deadline = None
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
    now = time.time()
    timestamps = REQUEST_TIMES.setdefault(ip, deque())
    while timestamps and now - timestamps[0] > RATE_WINDOW:
        timestamps.popleft()
    if len(timestamps) >= RATE_LIMIT:
        raise web.HTTPTooManyRequests(text="Too many game requests. Please wait a moment.")
    timestamps.append(now)


def lobby_snapshot():
    public = [room for room in ROOMS.values() if room.public]
    waiting = [r for r in public if r.status == "waiting" and
               (r.connected("black") or time.time() - r.modified < 30)]
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
    path = ROOT / "index.html" if (ROOT / "index.html").exists() else ROOT / "static" / "index.html"
    if os.getenv("GO13_PREVIEW") == "true":
        html = path.read_text().replace("<title>13GO v1.1", "<title>13GO Test v1.1")
        html = html.replace('<section id="homePage" aria-label="Home">', '<section id="homePage" aria-label="Home"><p style="text-align:center;color:#a9b6cc;font-size:12px">Test v1.1 · Temporary games</p>')
        return web.Response(text=html, content_type="text/html", headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"})
    return web.FileResponse(path)


async def health(request):
    try:
        async with asyncio.timeout(2):
            async with request.app[LOCK]:
                await request.app[STORE].ping()
    except Exception:
        return web.json_response({"ok": False, "version": VERSION}, status=503)
    return web.json_response({"ok": True, "version": VERSION, "rooms": len(ROOMS), "storage": request.app[STORE].backend})


async def lobby(request):
    return web.json_response(lobby_snapshot())


async def create_room(request):
    check_rate(request)
    data = await input_json(request)
    async with request.app[LOCK]:
        room = new_room(public=bool(data.get("public", False)), solo=data.get("solo") is True)
        role, token = room.claim(None, request_name(data))
        try:
            await request.app[STORE].save(room)
        except Exception:
            ROOMS.pop(room.code, None)
            raise web.HTTPServiceUnavailable(text="Unable to save this game. Please try again.")
    return web.json_response({"room": room.code, "token": token, "role": role})


async def match_room(request):
    check_rate(request)
    data = await input_json(request)
    async with request.app[LOCK]:
        now = time.time()
        candidates = [r for r in ROOMS.values() if r.public and r.status == "waiting"
                      and r.players["black"] is not None and r.players["white"] is None
                      and (r.connected("black") or now - r.modified < 30)]
        room = min(candidates, key=lambda r: (not r.connected("black"), r.modified)) if candidates else new_room(public=True)
        before = room.snapshot()
        role, token = room.claim(None, request_name(data))
        room.connection_changed()
        try:
            await request.app[STORE].save(room)
        except Exception as exc:
            room.restore(exc.snapshot if isinstance(exc, StaleRoom) else before)
            if not room.players["black"]:
                ROOMS.pop(room.code, None)
            raise web.HTTPServiceUnavailable(text="Unable to save this game. Please try again.")
        await room.broadcast()
    return web.json_response({"room": room.code, "token": token, "role": role, "matched": role == "white"})


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
            now = time.time()
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
                async with request.app[LOCK]:
                    if room is None:
                        if data.get("type") != "join":
                            raise ValueError("Join a game first.")
                        code = str(data.get("room", "")).upper()
                        candidate = ROOMS.get(code)
                        if not candidate:
                            raise ValueError("Game not found. Please start a new game.")
                        before = candidate.snapshot()
                        token = data.get("token") if isinstance(data.get("token"), str) else None
                        name = request_name(data)
                        if data.get("mode") == "watch" or candidate.status == "cancelled":
                            role, token = "spectator", None
                        else:
                            role, token = candidate.claim(token, name)
                        if role == "spectator" and sum(r == "spectator" for r in candidate.clients.values()) >= MAX_SPECTATORS_PER_ROOM:
                            candidate.restore(before)
                            raise ValueError("This game has reached its spectator limit.")
                        candidate.clients[socket] = role
                        candidate.connection_changed()
                        try:
                            await request.app[STORE].save(candidate)
                        except Exception as exc:
                            candidate.clients.pop(socket, None)
                            candidate.restore(exc.snapshot if isinstance(exc, StaleRoom) else before)
                            await socket.send_json({"type": "error", "message": "Unable to save this game. Reconnect shortly."})
                            continue
                        room = candidate
                        await socket.send_json({"type": "welcome", "role": role, "token": token, "room": code})
                        await room.broadcast()
                    else:
                        before = room.snapshot()
                        room.act(role, data)
                        try:
                            await request.app[STORE].save(room)
                        except Exception as exc:
                            room.restore(exc.snapshot if isinstance(exc, StaleRoom) else before)
                            await socket.send_json({"type": "error", "message": "Move not saved. Please try again."})
                            continue
                        await room.broadcast()
            except (ValueError, json.JSONDecodeError) as exc:
                await socket.send_json({"type": "error", "message": str(exc)})
    finally:
        if room:
            async with request.app[LOCK]:
                room.clients.pop(socket, None)
                room.connection_changed()
                try:
                    await request.app[STORE].save(room)
                except Exception:
                    logging.exception("Unable to save disconnection state")
                await room.broadcast()
    return socket


async def cleanup_loop(app):
    try:
        while True:
            await asyncio.sleep(1)
            async with app[LOCK]:
                now = time.time()
                for code, room in list(ROOMS.items()):
                    before = room.snapshot()
                    if room.tick(now):
                        try:
                            await app[STORE].save(room)
                        except Exception as exc:
                            room.restore(exc.snapshot if isinstance(exc, StaleRoom) else before)
                            logging.exception("Unable to save timeout")
                            continue
                        await room.broadcast()
                    # Keep finished room links for 30 days, active rooms for 7 days.
                    stale = 180 if room.status in ("waiting", "cancelled") else 30 * 86400 if room.status == "finished" else 7 * 86400
                    if not room.clients and now - room.modified > stale:
                        try:
                            await app[STORE].delete(code)
                        except Exception:
                            continue
                        ROOMS.pop(code, None)
    except asyncio.CancelledError:
        pass


STORE = web.AppKey("store", RoomStore)
LOCK = web.AppKey("room_lock", asyncio.Lock)


async def cleanup_context(app):
    store = app[STORE]
    await store.open()
    ROOMS.clear()
    for payload in await store.load():
        room = Room.from_snapshot(payload)
        room.connection_changed()
        ROOMS[room.code] = room
    task = asyncio.create_task(cleanup_loop(app))
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await store.close()


def make_app(store=None):
    app = web.Application(client_max_size=2048)
    app[STORE] = store or RoomStore()
    app[LOCK] = asyncio.Lock()
    app.router.add_get("/", index)
    app.router.add_post("/api/rooms", create_room)
    app.router.add_post("/api/match", match_room)
    app.router.add_get("/api/lobby", lobby)
    app.router.add_get("/health", health)
    app.router.add_get("/ws", websocket_handler)
    if (ROOT / "static").exists():
        app.router.add_static("/static/", ROOT / "static", show_index=False)
    app.cleanup_ctx.append(cleanup_context)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"13GO: http://localhost:{port}")
    web.run_app(make_app(), host="0.0.0.0", port=port)

