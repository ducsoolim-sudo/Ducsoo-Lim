import os
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
import server as s

class StandardAI(unittest.IsolatedAsyncioTestCase):
    async def test_removed_levels_are_rejected(self):
        with patch.dict(os.environ, {'GO13_PREVIEW':'true'}):
            client=TestClient(TestServer(s.make_app(s.RoomStore(path=':memory:',database_url=''))))
            await client.start_server()
            try:
                for level in ('medium','low','invalid'):
                    response=await client.post('/api/test-match',json={'level':level})
                    self.assertEqual(response.status,400)
            finally:
                await client.close()
