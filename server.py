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
import auth
from scoring import automatic_dead, territory_score
from adjudicator import KataGo, settled_adjudication
import rules_policy as policy
from preview_bot import run_bot

N = 13
KOMI = 6.5
VERSION = "1.1.0"
MAIN_SECONDS = 300.0
INCREMENT = 3.0
DISCONNECT_GRACE = 90.0
REVIEW_SECONDS = policy.REVIEW_SECONDS
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
        self.time_policy = policy.POLICY
        self.periods = {"black": policy.BYOYOMI_PERIODS, "white": policy.BYOYOMI_PERIODS}
        self.game_started_at = None
        self.departures = {"black": 0, "white": 0}
        self.offline_used = {"black": 0.0, "white": 0.0}
        self.absence_counted = {"black": False, "white": False}
        self.test_bot = False
        self.rules = "Japanese"
        self.adjudication = None
        self.ko_position = None
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
        self.score_uncertain: set[int] = set()
        self.approvals: set[str] = set()
        self.rematch: set[str] = set()
        self.result: dict | None = None
        self.modified = time.time()
        self.created = time.time()
        self.remaining = {"black": MAIN_SECONDS, "white": MAIN_SECONDS}
        self.turn_started = None
        self.recovery_anchor = None
        self.review_deadline = None
        self.scoring_notice = None
        self.absent_since = {"black": None, "white": None}

    def snapshot(self):
        data = copy.deepcopy({k: v for k, v in self.__dict__.items() if k != "clients"})
        for key in ("history", "dead", "approvals", "rematch", "score_uncertain"):
            data[key] = list(data[key])
        return data

    def restore(self, data):
        for key, value in copy.deepcopy(data).items():
            if key != "clients":
                setattr(self, key, value)
        for key in ("history", "dead", "approvals", "rematch", "score_uncertain"):
            setattr(self, key, set(getattr(self, key, ())))

    @classmethod
    def from_snapshot(cls, data):
        room = cls(data["code"])
        room.restore(data)
        if "time_policy" not in data:
            room.time_policy = "fischer-v1"
        if "rules" not in data:
            room.rules = "Chinese"
        return room

    def recover_after_restart(self, persisted_at):
        # Freeze at the last durable state; never charge unknown server downtime.
        if not self.solo and self.status in ('playing', 'scoring'):
            if self.recovery_anchor is None:
                self.recovery_anchor = persisted_at

    def clock(self, now=None):
        now = time.time() if now is None else now
        wall_now = now
        if self.recovery_anchor is not None:
            now = self.recovery_anchor
        remaining = self.remaining.copy()
        main_remaining = self.remaining.copy()
        periods = self.periods.copy()
        role = "black" if self.turn == 1 else "white"
        if self.status == "playing" and self.turn_started is not None:
            if self.time_policy == policy.POLICY:
                main_remaining[role], periods[role], remaining[role] = policy.project_clock(self.remaining[role], self.periods[role], now-self.turn_started)
            else:
                remaining[role] = max(0.0, remaining[role] - max(0.0, now - self.turn_started))
        if self.time_policy == policy.POLICY:
            for side in ('black', 'white'):
                if side != role or self.status != 'playing' or self.turn_started is None:
                    remaining[side] = self.remaining[side] if self.remaining[side]>0 else policy.BYOYOMI_SECONDS if self.periods[side]>0 else 0
        elapsed = max(0, now-self.turn_started) if self.turn_started is not None else 0
        warning = self.time_policy == policy.POLICY and self.status == 'playing' and main_remaining[role]>0 and elapsed>=policy.IDLE_WARNING_SECONDS
        return {"remaining": remaining, "running": role if self.status == "playing" and self.turn_started is not None and self.recovery_anchor is None else None,
                "increment": INCREMENT if self.time_policy != policy.POLICY else 0, "serverTime": wall_now, "reviewDeadline": self.review_deadline if self.recovery_anchor is None else None,
                "recovering": self.recovery_anchor is not None,
                "policy": self.time_policy, "mainRemaining": main_remaining, "periods": periods,
                "byoyomiSeconds": policy.BYOYOMI_SECONDS, "idleWarning": role if warning else None,
                "turnElapsed": elapsed}

    def tick(self, now=None):
        now = time.time() if now is None else now
        if self.recovery_anchor is not None or self.solo or self.status not in ("playing", "scoring"):
            return False
        if self.status == "playing" and self.turn_started is not None:
            role = "black" if self.turn == 1 else "white"
            clock = self.clock(now)
            reason = None
            if self.time_policy == policy.POLICY:
                elapsed = now-self.turn_started
                if self.moves == 0 and elapsed >= policy.FIRST_ACTION_SECONDS:
                    reason = 'first_move_timeout'
                elif clock['mainRemaining'][role]>0 and elapsed>=policy.IDLE_LOSS_SECONDS:
                    reason = 'move_delay'
            if reason or clock["remaining"][role] <= 0:
                if self.time_policy == policy.POLICY:
                    self.remaining[role] = clock['mainRemaining'][role]
                    self.periods[role] = clock['periods'][role]
                else:
                    self.remaining[role] = 0
                self.result = {"reason": reason or "time", "winner": "white" if role == "black" else "black"}
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
        changed = False
        for role in ("black", "white"):
            changed = self.count_absence(role, now) or changed
            other = "white" if role == "black" else "black"
            absent = self.absent_since[role]
            elapsed = max(0, now-absent) if absent is not None else 0
            repeated = self.time_policy == policy.POLICY and self.departures[role]>=policy.DISCONNECT_LIMIT
            budget = self.offline_used[role]+elapsed if self.time_policy == policy.POLICY else elapsed
            if (repeated or (absent is not None and budget>=DISCONNECT_GRACE)) and self.connected(other):
                if self.turn_started is None and self.moves == 0:
                    self.status = "cancelled"
                else:
                    self.result = {"reason": "repeated_departure" if repeated else "disconnect", "winner": other}
                    self.status = "finished"
                    self.turn_started = None
                return True
        return changed

    def count_absence(self, role, now):
        absent = self.absent_since[role]
        if (self.time_policy == policy.POLICY and self.game_started_at is not None
                and self.status in ('playing', 'scoring') and absent is not None
                and not self.absence_counted[role] and now-absent>=policy.DISCONNECT_EPISODE_SECONDS):
            self.departures[role] += 1
            self.absence_counted[role] = True
            return True
        return False

    def connection_changed(self):
        now = time.time()
        if self.solo:
            return
        if self.recovery_anchor is not None:
            if not all(self.connected(r) for r in ('black', 'white')):
                return
            offset = max(0, now - self.recovery_anchor)
            for key in ('turn_started', 'review_deadline', 'game_started_at'):
                value = getattr(self, key)
                if value is not None:
                    setattr(self, key, value + offset)
            for role in ('black', 'white'):
                if self.absent_since[role] is not None:
                    self.absent_since[role] += offset
            self.recovery_anchor = None
        for role in ("black", "white"):
            self.count_absence(role, now)
            if self.connected(role):
                if self.absent_since[role] is not None and self.game_started_at is not None:
                    self.offline_used[role] += max(0, now-self.absent_since[role])
                self.absent_since[role] = None
                self.absence_counted[role] = False
            elif self.players[role] and self.absent_since[role] is None:
                self.absent_since[role] = now
                self.absence_counted[role] = False
        if self.status == "playing" and self.turn_started is None and self.moves == 0 and all(self.connected(r) for r in ("black", "white")):
            self.turn_started = now
            self.game_started_at = now
            self.absent_since = {"black": None, "white": None}

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
            "testBot": self.test_bot,
            "spectators": sum(role == "spectator" and not ws.closed for ws, role in self.clients.items()),
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
            "departures": self.departures,
            "offlineUsed": self.offline_used,
            "absentSince": self.absent_since,
            "lastMove": self.last_move,
            "dead": sorted(self.dead),
            "approvals": sorted(self.approvals),
            "rematch": sorted(self.rematch),
            "score": self.calculate_score() if self.status == "scoring" and (self.rules != "Japanese" or self.adjudication and self.adjudication.get("status") == "ready") and not self.score_uncertain and not (self.adjudication and self.adjudication.get("status") in ("analyzing", "review", "unavailable")) else None,
            "rules": self.rules,
            "scoreUncertain": sorted(self.score_uncertain),
            "scoringNotice": self.scoring_notice,
            "adjudication": self.adjudication,
            "result": self.result,
        }

    def calculate_score(self):
        if self.adjudication and self.adjudication.get("status") in ("ready", "review"):
            return self.adjudication["score"]
        if self.rules == "Chinese":
            return area_score(self.board, self.dead)
        return territory_score(self.board, self.dead, self.captures)

    def sgf(self) -> str:
        def escape(value):
            return str(value).replace("\\", "\\\\").replace("]", "\\]").replace("\r", " ").replace("\n", " ")
        headers = "(;GM[1]FF[4]CA[UTF-8]AP[13GO]SZ[13]KM[6.5]RU[" + self.rules + "]"
        if self.time_policy == policy.POLICY:
            headers += "TM[300]OT[3x30 byo-yomi]"
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
        if self.recovery_anchor is not None:
            raise ValueError("Waiting for both players to reconnect.")
        now = time.time()
        if self.tick(now) and self.status in ("finished", "cancelled"):
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
                previous = board_hash(self.board)
                forbidden = ({self.ko_position} if self.ko_position else set()) if self.rules == "Japanese" else self.history
                self.board, captured = try_move(self.board, index, self.turn, forbidden)
                self.ko_position = previous
                self.history.add(board_hash(self.board))
                self.captures[role] += captured
                self.last_move = index
                self.passes = 0
            else:
                self.ko_position = None
                self.passes += 1
                self.last_move = None
            if not self.solo:
                if self.time_policy == policy.POLICY:
                    self.remaining[role], self.periods[role], _ = policy.project_clock(self.remaining[role], self.periods[role], now-self.turn_started if self.turn_started is not None else 0)
                else:
                    self.remaining[role] = self.clock(now)["remaining"][role] + INCREMENT
                self.turn_started = now
            self.scoring_notice = None
            self.move_record.append((self.turn, index if kind == "move" else None))
            self.moves += 1
            self.turn *= -1
            if self.passes == 2:
                self.status = "scoring"
                self.turn_started = None
                self.review_deadline = None if self.solo else now + REVIEW_SECONDS
                self.dead, self.score_uncertain = automatic_dead(self.board) if self.rules == "Japanese" else (set(), set())
                if self.rules == "Japanese":
                    proof = settled_adjudication(self.board, self.captures)
                    self.adjudication = proof or {"status": "pending"}
                    if proof:
                        self.dead = set(proof['dead'])
                        self.score_uncertain.clear()
                    else:
                        self.review_deadline = None
                elif self.time_policy == policy.POLICY and self.score_uncertain:
                    self.review_deadline = None
                self.approvals.clear()
        elif kind == "dead":
            raise ValueError("Dead stones are determined automatically.")
        elif kind == "approve":
            if self.status != "scoring":
                raise ValueError("The score can only be accepted during scoring.")
            if self.rules == "Japanese" and (not self.adjudication or self.adjudication.get("status") != "ready"):
                raise ValueError("The score has not been verified yet.")
            if self.score_uncertain or (self.adjudication and self.adjudication.get("status") in ("analyzing", "review", "unavailable")):
                raise ValueError("The position is not settled. The score cannot be confirmed.")
            self.approvals.update(("black", "white") if self.solo else (role,))
            if len(self.approvals) == 2:
                self.result = {"reason": "score", **self.calculate_score()}
                self.status = "finished"
        elif kind == "resume":
            if self.status != "scoring":
                raise ValueError("This game cannot be resumed right now.")
            self.adjudication = None
            self.status = "playing"
            self.turn_started = None if self.solo else now
            self.review_deadline = None
            self.passes = 0
            self.dead.clear()
            self.score_uncertain.clear()
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
                self.ko_position = None
                self.turn = 1
                self.status = "playing"
                self.captures = {"black": 0, "white": 0}
                self.passes = 0
                self.moves = 0
                self.adjudication = None
                self.move_record.clear()
                self.last_move = None
                self.dead.clear()
                self.score_uncertain.clear()
                self.approvals.clear()
                self.rematch.clear()
                self.result = None
                self.remaining = {"black": MAIN_SECONDS, "white": MAIN_SECONDS}
                self.periods = {"black": policy.BYOYOMI_PERIODS, "white": policy.BYOYOMI_PERIODS}
                self.departures = {"black": 0, "white": 0}
                self.offline_used = {"black": 0.0, "white": 0.0}
                self.absence_counted = {"black": False, "white": False}
                self.absent_since = {"black": None, "white": None}
                self.game_started_at = now
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
            "spectators": sum(role == "spectator" and not ws.closed for ws, role in r.clients.items()),
            "moves": r.moves,
        } for r in visible[:32]],
    }


async def index(request):
    path = ROOT / "index.html" if (ROOT / "index.html").exists() else ROOT / "static" / "index.html"
    if os.getenv("GO13_PREVIEW") == "true":
        html = path.read_text().replace("<title>13GO v1.1", "<title>13GO Test v1.1")
        html = html.replace('id="testMatch" class="button secondary hidden"', 'id="testMatch" class="button secondary"')
        html = html.replace('13GO / V1.1', 'TEST V1.1 · Temporary games')
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


async def test_match(request):
    if os.getenv('GO13_PREVIEW') != 'true':
        raise web.HTTPNotFound()
    check_rate(request)
    if len(request.app[BOT_JOBS]) >= 8:
        raise web.HTTPServiceUnavailable(text='Test opponents are busy. Please retry shortly.')
    data = await input_json(request)
    async with request.app[LOCK]:
        room = new_room(public=False, solo=False)
        room.test_bot = True
        role, token = room.claim(None, request_name(data))
        try:
            await request.app[STORE].save(room)
        except Exception:
            ROOMS.pop(room.code,None)
            raise web.HTTPServiceUnavailable(text='Unable to start test game.')
    port = request.transport.get_extra_info('sockname')[1]
    ready = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(run_bot(port,room.code,ready,try_move,board_hash))
    request.app[BOT_JOBS][room.code] = task
    task.add_done_callback(lambda _: request.app[BOT_JOBS].pop(room.code,None))
    try:
        await asyncio.wait_for(ready,8)
    except Exception:
        task.cancel()
        async with request.app[LOCK]:
            room.status='cancelled'
            await request.app[STORE].save(room)
        raise web.HTTPServiceUnavailable(text='Test opponent unavailable. Please retry.')
    return web.json_response({'room':room.code,'token':token,'role':role,'testBot':True})


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
                            user = await auth.identity(request, request.app[STORE])
                            if user and role in ('black', 'white'):
                                owner = candidate.players[role].get('account_id')
                                if owner and owner != user['id']:
                                    candidate.restore(before)
                                    raise ValueError('This seat belongs to another account.')
                                candidate.players[role]['account_id'] = user['id']
                        if role == "spectator" and sum(r == "spectator" for r in candidate.clients.values()) >= MAX_SPECTATORS_PER_ROOM:
                            candidate.restore(before)
                            raise ValueError("This game has reached its spectator limit.")
                        candidate.clients[socket] = role
                        candidate.connection_changed()
                        if before.get("recovery_anchor") is not None and candidate.recovery_anchor is None:
                            schedule_adjudication(request.app, candidate)
                        try:
                            await request.app[STORE].save(candidate)
                        except Exception as exc:
                            candidate.clients.pop(socket, None)
                            candidate.restore(exc.snapshot if isinstance(exc, StaleRoom) else before)
                            await socket.send_json({"type": "error", "message": "Unable to save this game. Reconnect shortly."})
                            continue
                        room = candidate
                        # A seat has one controlling connection. Retire the old
                        # socket only after the replacement join is durable.
                        if role in ("black", "white"):
                            for previous, previous_role in tuple(room.clients.items()):
                                if previous is not socket and previous_role == role:
                                    room.clients.pop(previous, None)
                                    closing = asyncio.create_task(previous.close(code=4001, message=b"Seat reconnected elsewhere"))
                                    request.app[JOBS].add(closing)
                                    closing.add_done_callback(request.app[JOBS].discard)
                        await socket.send_json({"type": "welcome", "role": role, "token": token, "room": code})
                        await room.broadcast()
                    else:
                        if room.clients.get(socket) != role:
                            raise ValueError("This connection no longer controls the seat. Reconnect to continue.")
                        before = room.snapshot()
                        room.act(role, data)
                        if room.status == 'scoring' and before['status'] != 'scoring':
                            schedule_adjudication(request.app, room)
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


BOT_JOBS = web.AppKey("preview_bots", dict)
ENGINE = web.AppKey("engine", KataGo)
JOBS = web.AppKey("adjudication_jobs", set)


def continue_unsettled(room, notice):
    room.act("black" if room.solo or room.turn == 1 else "white", {"type": "resume"})
    room.scoring_notice = notice


def schedule_adjudication(app, room):
    if room.recovery_anchor is not None or room.rules != "Japanese" or room.status != "scoring":
        return
    if room.adjudication and room.adjudication.get("status") == "ready":
        return
    proof = settled_adjudication(room.board, room.captures)
    if proof:
        room.adjudication = proof
        room.dead = set(proof['dead'])
        room.score_uncertain.clear()
        room.approvals.clear()
        room.review_deadline = None if room.solo else time.time() + REVIEW_SECONDS
        return
    if not app[ENGINE].configured:
        continue_unsettled(room, "Position not settled. Continue playing.")
        return
    if room.adjudication and room.adjudication.get("status") not in ("pending", "analyzing"):
        continue_unsettled(room, "Position not settled. Continue playing.")
        return
    # Mark before another event can accept the preliminary heuristic score.
    room.adjudication = {"status": "analyzing", "job": secrets.token_urlsafe(12)}
    room.review_deadline = None
    game_id = room.game_id
    snapshot = Room.from_snapshot(room.snapshot())
    marker = room.adjudication

    async def run():
        try:
            result = await app[ENGINE].analyze(snapshot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Automatic adjudication unavailable")
            result = {"status": "unavailable"}
        retry_delay = 1
        while True:
            async with app[LOCK]:
                if (room.status != "scoring" or room.game_id != game_id
                        or not room.adjudication
                        or room.adjudication.get("job") != marker["job"]
                        or room.recovery_anchor is not None):
                    return
                before = room.snapshot()
                room.adjudication = result
                room.approvals.clear()
                if result['status'] in ('ready', 'review'):
                    room.dead = set(result['dead'])
                    room.score_uncertain = set(result['uncertain'])
                # Only a durably saved result may start the confirmation budget.
                # Reset its deadline on each attempt so storage downtime cannot
                # consume the player's review time.
                room.review_deadline = time.time() + REVIEW_SECONDS if result['status'] == 'ready' and not room.solo else None
                if result['status'] != 'ready':
                    continue_unsettled(room, "Score check unavailable. Continue playing." if result['status'] == 'unavailable' else "Position not settled. Continue playing.")
                try:
                    await app[STORE].save(room)
                except StaleRoom as exc:
                    # A newer writer owns this state; never apply an old result.
                    room.restore(exc.snapshot)
                    logging.exception("Automatic adjudication superseded by a newer save")
                    return
                except Exception:
                    room.restore(before)
                    logging.exception("Unable to save automatic adjudication; retrying")
                else:
                    await room.broadcast()
                    return
            # Keep the analyzed result, not the global room lock, while storage
            # recovers. Cancellation and state/game changes invalidate retries.
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)
    task = asyncio.create_task(run())
    app[JOBS].add(task)
    task.add_done_callback(app[JOBS].discard)


STORE = web.AppKey("store", RoomStore)
LOCK = web.AppKey("room_lock", asyncio.Lock)


async def cleanup_context(app):
    store = app[STORE]
    await store.open()
    await store.init_accounts()
    ROOMS.clear()
    for payload in await store.load():
        room = Room.from_snapshot(payload)
        room.recover_after_restart(payload["persisted_at"])
        room.connection_changed()
        ROOMS[room.code] = room
    for room in ROOMS.values():
        schedule_adjudication(app, room)
    task = asyncio.create_task(cleanup_loop(app))
    yield
    task.cancel()
    for job in list(app[BOT_JOBS].values()):
        job.cancel()
    await asyncio.gather(*list(app[BOT_JOBS].values()),return_exceptions=True)
    for job in app[JOBS]:
        job.cancel()
    await asyncio.gather(task, *app[JOBS], return_exceptions=True)
    await store.close()


async def shutdown_preview_bots(app):
    jobs=list(app[BOT_JOBS].values())
    for job in jobs:job.cancel()
    await asyncio.gather(*jobs,return_exceptions=True)


def make_app(store=None):
    app = web.Application(client_max_size=16384)
    app[STORE] = store or RoomStore()
    app[LOCK] = asyncio.Lock()
    app[ENGINE] = KataGo()
    app[JOBS] = set()
    app[BOT_JOBS] = {}
    auth.setup(app, STORE)
    app.router.add_get("/", index)
    app.router.add_post("/api/rooms", create_room)
    app.router.add_post("/api/match", match_room)
    app.router.add_post("/api/test-match", test_match)
    app.router.add_get("/api/lobby", lobby)
    app.router.add_get("/health", health)
    app.router.add_get("/ws", websocket_handler)
    if (ROOT / "static").exists():
        app.router.add_static("/static/", ROOT / "static", show_index=False)
    app.cleanup_ctx.append(cleanup_context)
    app.on_shutdown.append(shutdown_preview_bots)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"13GO: http://localhost:{port}")
    web.run_app(make_app(), host="0.0.0.0", port=port)

