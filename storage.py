"""Single-worker durable room store. Secrets stay in DATABASE_URL, never in source."""
from datetime import datetime, timezone
import json
import os
import sqlite3
import time


class StaleRoom(Exception):
    def __init__(self, snapshot):
        self.snapshot = snapshot
        super().__init__('A newer game state was saved by another server.')


class RoomStore:
    def __init__(self, path=None, database_url=None):
        self.url = database_url if database_url is not None else os.getenv('DATABASE_URL', '')
        self.path = path or os.getenv('ROOM_DB_PATH', 'go13.sqlite3')
        self.connection = None
        self.backend = 'postgresql' if self.url else 'sqlite'

    async def open(self):
        if self.url:
            import psycopg
            self.connection = await psycopg.AsyncConnection.connect(self.url, autocommit=True, connect_timeout=10, options="-c statement_timeout=5000")
            await self.connection.execute('CREATE TABLE IF NOT EXISTS go13_rooms (code TEXT PRIMARY KEY, payload TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL, revision INTEGER NOT NULL DEFAULT 0)')
            await self.connection.execute('CREATE TABLE IF NOT EXISTS go13_games (game_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL)')
        else:
            if os.getenv('RENDER') == 'true' and os.getenv('GO13_PREVIEW') != 'true':
                raise RuntimeError('DATABASE_URL is required on Render to preserve games across deploys.')
            self.connection = sqlite3.connect(self.path)
            self.connection.execute('PRAGMA journal_mode=WAL')
            self.connection.execute('CREATE TABLE IF NOT EXISTS go13_rooms (code TEXT PRIMARY KEY, payload TEXT NOT NULL, updated REAL NOT NULL, revision INTEGER NOT NULL DEFAULT 0)')
            self.connection.execute('CREATE TABLE IF NOT EXISTS go13_games (game_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated REAL NOT NULL)')
            self.connection.commit()

    async def auth_query(self, sql, values=()):
        if self.url:
            cursor = await self.connection.execute(sql.replace('?', '%s'), values)
            return await cursor.fetchall() if cursor.description else []
        with self.connection:
            cursor = self.connection.execute(sql, values)
            return cursor.fetchall() if cursor.description else []

    async def auth_get(self, key):
        rows = await self.auth_query('SELECT payload FROM go13_auth WHERE key=? AND expires>?', (key, time.time()))
        return json.loads(rows[0][0]) if rows else None

    async def auth_put(self, key, value, expires):
        await self.auth_query('DELETE FROM go13_auth WHERE expires<?', (time.time(),))
        await self.auth_query('INSERT INTO go13_auth VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,expires=excluded.expires', (key, json.dumps(value), expires))

    async def account_history(self, subject):
        rows = await self.auth_query('SELECT payload FROM go13_account_games WHERE subject=? ORDER BY updated DESC LIMIT 200', (subject,))
        return [json.loads(row[0]) for row in rows]

    async def profile_get(self, key):
        rows = await self.auth_query('SELECT payload FROM go13_profiles WHERE key=?', (key,))
        return json.loads(rows[0][0]) if rows else None

    async def profile_put(self, key, profile):
        await self.auth_query('INSERT INTO go13_profiles VALUES (?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload', (key, json.dumps(profile)))

    async def init_accounts(self):
        await self.auth_query('CREATE TABLE IF NOT EXISTS go13_profiles (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        await self.auth_query('CREATE TABLE IF NOT EXISTS go13_auth (key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL)')
        await self.auth_query('CREATE TABLE IF NOT EXISTS go13_account_games (subject TEXT NOT NULL, game_id TEXT NOT NULL, payload TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL, PRIMARY KEY(subject,game_id))')

    async def load(self):
        if self.url:
            cursor = await self.connection.execute('SELECT payload, updated FROM go13_rooms ORDER BY updated DESC')
            rows = await cursor.fetchall()
        else:
            rows = self.connection.execute('SELECT payload, updated FROM go13_rooms ORDER BY updated DESC').fetchall()
        return [dict(json.loads(row[0]), persisted_at=row[1]) for row in rows]

    async def save(self, room):
        snapshot = room.snapshot()
        snapshot['revision'] = room.revision + 1
        values = (room.code, json.dumps(snapshot), time.time(), room.revision + 1, room.revision)
        archive = (room.game_id, json.dumps(room.state()), time.time()) if room.status == 'finished' else None
        locked_profiles = []
        if room.status == 'playing' and not room.solo and not room.test_bot:
            for player in room.players.values():
                if player and player.get('profile_key'):
                    profile = await self.profile_get(player['profile_key'])
                    if profile and not profile['rankLocked']:
                        profile['rankLocked'] = True
                        locked_profiles.append((json.dumps(profile), player['profile_key']))
        account_records = []
        if archive and not room.solo and not room.test_bot:
            for color, player in room.players.items():
                if player and player.get('account_id'):
                    other = room.players['white' if color == 'black' else 'black'] or {}
                    record = dict(id=room.game_id, room=room.code, opponent=other.get('name', 'Player'), color=color, won=room.result['winner'] == color, reason=room.result.get('reason'), margin=room.result.get('margin'), moves=room.moves, sgf=room.sgf(), date=datetime.now(timezone.utc).isoformat())
                    account_records.append((player['account_id'], room.game_id, json.dumps(record), time.time()))
        if self.url:
            async with self.connection.transaction():
                cursor = await self.connection.execute('INSERT INTO go13_rooms (code,payload,updated,revision) VALUES (%s,%s,%s,%s) ON CONFLICT(code) DO UPDATE SET payload=excluded.payload,updated=excluded.updated,revision=excluded.revision WHERE go13_rooms.revision=%s RETURNING revision', values)
                if not await cursor.fetchone():
                    cursor = await self.connection.execute('SELECT payload FROM go13_rooms WHERE code=%s', (room.code,))
                    raise StaleRoom(json.loads((await cursor.fetchone())[0]))
                for record in locked_profiles:
                    await self.connection.execute('UPDATE go13_profiles SET payload=%s WHERE key=%s', record)
                if archive:
                    await self.connection.execute('INSERT INTO go13_games VALUES (%s,%s,%s) ON CONFLICT(game_id) DO NOTHING', archive)
                for record in account_records:
                    await self.connection.execute('INSERT INTO go13_account_games VALUES (%s,%s,%s,%s) ON CONFLICT(subject,game_id) DO NOTHING', record)
        else:
            with self.connection:
                cursor = self.connection.execute('INSERT INTO go13_rooms (code,payload,updated,revision) VALUES (?,?,?,?) ON CONFLICT(code) DO UPDATE SET payload=excluded.payload,updated=excluded.updated,revision=excluded.revision WHERE go13_rooms.revision=? RETURNING revision', values)
                if not cursor.fetchone():
                    row = self.connection.execute('SELECT payload FROM go13_rooms WHERE code=?', (room.code,)).fetchone()
                    raise StaleRoom(json.loads(row[0]))
                for record in locked_profiles:
                    self.connection.execute('UPDATE go13_profiles SET payload=? WHERE key=?', record)
                if archive:
                    self.connection.execute('INSERT INTO go13_games VALUES (?,?,?) ON CONFLICT(game_id) DO NOTHING', archive)
                for record in account_records:
                    self.connection.execute('INSERT INTO go13_account_games VALUES (?,?,?,?) ON CONFLICT(subject,game_id) DO NOTHING', record)

        room.revision += 1

    async def ping(self):
        if self.url:
            await self.connection.execute("SELECT 1")
        else:
            self.connection.execute("SELECT 1")

    async def delete(self, code):
        if self.url:
            await self.connection.execute('DELETE FROM go13_rooms WHERE code=%s', (code,))
        else:
            with self.connection:
                self.connection.execute('DELETE FROM go13_rooms WHERE code=?', (code,))

    async def close(self):
        if self.url:
            await self.connection.close()
        else:
            self.connection.close()
