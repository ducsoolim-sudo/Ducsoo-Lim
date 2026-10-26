"""Single-worker durable room store. Secrets stay in DATABASE_URL, never in source."""
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

    async def load(self):
        if self.url:
            cursor = await self.connection.execute('SELECT payload FROM go13_rooms ORDER BY updated DESC')
            rows = await cursor.fetchall()
        else:
            rows = self.connection.execute('SELECT payload FROM go13_rooms ORDER BY updated DESC').fetchall()
        return [json.loads(row[0]) for row in rows]

    async def save(self, room):
        snapshot = room.snapshot()
        snapshot['revision'] = room.revision + 1
        values = (room.code, json.dumps(snapshot), time.time(), room.revision + 1, room.revision)
        archive = (room.game_id, json.dumps(room.state()), time.time()) if room.status == 'finished' else None
        if self.url:
            async with self.connection.transaction():
                cursor = await self.connection.execute('INSERT INTO go13_rooms (code,payload,updated,revision) VALUES (%s,%s,%s,%s) ON CONFLICT(code) DO UPDATE SET payload=excluded.payload,updated=excluded.updated,revision=excluded.revision WHERE go13_rooms.revision=%s RETURNING revision', values)
                if not await cursor.fetchone():
                    cursor = await self.connection.execute('SELECT payload FROM go13_rooms WHERE code=%s', (room.code,))
                    raise StaleRoom(json.loads((await cursor.fetchone())[0]))
                if archive:
                    await self.connection.execute('INSERT INTO go13_games VALUES (%s,%s,%s) ON CONFLICT(game_id) DO NOTHING', archive)
        else:
            with self.connection:
                cursor = self.connection.execute('INSERT INTO go13_rooms (code,payload,updated,revision) VALUES (?,?,?,?) ON CONFLICT(code) DO UPDATE SET payload=excluded.payload,updated=excluded.updated,revision=excluded.revision WHERE go13_rooms.revision=? RETURNING revision', values)
                if not cursor.fetchone():
                    row = self.connection.execute('SELECT payload FROM go13_rooms WHERE code=?', (room.code,)).fetchone()
                    raise StaleRoom(json.loads(row[0]))
                if archive:
                    self.connection.execute('INSERT INTO go13_games VALUES (?,?,?) ON CONFLICT(game_id) DO NOTHING', archive)

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
