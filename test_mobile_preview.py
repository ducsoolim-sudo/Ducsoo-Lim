import os,unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
import server as s
class MobilePreview(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client=TestClient(TestServer(s.make_app(s.RoomStore(path=':memory:',database_url=''))));await self.client.start_server()
    async def asyncTearDown(self):await self.client.close()
    async def test_preview_bridge_is_isolated_from_web_and_production(self):
        with patch.dict(os.environ,{'GO13_PREVIEW':'true'}):
            web=await (await self.client.get('/')).text();self.assertNotIn('<script src="/static/mobile-bridge.js">',web)
            response=await self.client.get('/mobile-preview');self.assertEqual(response.status,200)
            html=await response.text();self.assertIn('<script src="/static/mobile-bridge.js">',html)
            self.assertLess(html.index('/static/mobile-bridge.js'),html.index('const N=13'))
            self.assertIn('noindex',response.headers['X-Robots-Tag'])
            self.assertEqual((await self.client.get('/static/mobile-bridge.js')).status,200)
        with patch.dict(os.environ,{'GO13_PREVIEW':''}):
            self.assertEqual((await self.client.get('/mobile-preview')).status,404)
            self.assertEqual((await self.client.get('/static/mobile-bridge.js')).status,404)
