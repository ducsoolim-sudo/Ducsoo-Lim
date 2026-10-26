import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from storage import RoomStore
import server


class PreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_render_requires_database_unless_explicit_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'RENDER': 'true', 'GO13_PREVIEW': 'false'}):
                store = RoomStore(path=str(Path(folder) / 'preview.sqlite3'), database_url='')
                with self.assertRaises(RuntimeError):
                    await store.open()
            with patch.dict(os.environ, {'RENDER': 'true', 'GO13_PREVIEW': 'true'}):
                await store.open()
                self.assertEqual(store.backend, 'sqlite')
                await store.close()

    async def test_preview_response_marked_and_not_indexed(self):
        with patch.dict(os.environ, {'GO13_PREVIEW': 'true'}):
            response = await server.index(None)
            self.assertIn('Test v1.1', response.text)
            self.assertIn('Temporary games', response.text)
            self.assertEqual(response.headers['X-Robots-Tag'], 'noindex, nofollow')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
