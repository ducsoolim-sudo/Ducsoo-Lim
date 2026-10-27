import unittest
from aiohttp.test_utils import TestClient, TestServer
import server as s


class SpectatorCounts(unittest.IsolatedAsyncioTestCase):
    async def test_join_leave_updates_count_on_player_socket(self):
        client=TestClient(TestServer(s.make_app(s.RoomStore(path=':memory:',database_url=''))))
        await client.start_server()
        try:
            player=await (await client.post('/api/match',json={'name':'A'})).json()
            ws=await client.ws_connect('/ws');await ws.send_json({'type':'join',**player})
            await ws.receive_json();self.assertEqual((await ws.receive_json())['state']['spectators'],0)
            viewer=await client.ws_connect('/ws');await viewer.send_json({'type':'join','room':player['room'],'mode':'watch'})
            await viewer.receive_json()
            self.assertEqual((await viewer.receive_json())['state']['spectators'],1)
            self.assertEqual((await ws.receive_json())['state']['spectators'],1)
            await viewer.close()
            self.assertEqual((await ws.receive_json())['state']['spectators'],0)
            await ws.close()
        finally:await client.close()

    async def test_closed_sockets_and_players_are_not_spectators(self):
        class Socket:
            def __init__(self,closed):self.closed=closed
        room=s.Room('COUNT');room.clients={Socket(False):'black',Socket(False):'white',Socket(False):'spectator',Socket(True):'spectator'}
        self.assertEqual(room.state()['spectators'],1)
