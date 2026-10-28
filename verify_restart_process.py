import asyncio,json,os,sys,tempfile
from pathlib import Path
import aiohttp
ROOT=Path('/workspace/scratch/333f3e35d031/Ducsoo-Lim')
async def state(ws):
 while True:
  d=await ws.receive_json(timeout=10)
  if d.get('type')=='state':return d.get('state',d)
async def start(db):
 env=dict(os.environ,PORT='18085',ROOM_DB_PATH=db,DATABASE_URL='',RENDER='false')
 p=await asyncio.create_subprocess_exec(sys.executable,'server.py',cwd=ROOT,env=env,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
 async with aiohttp.ClientSession() as c:
  for _ in range(100):
   try:
    async with c.get('http://127.0.0.1:18085/health') as r:
     if r.status==200:return p
   except aiohttp.ClientError:pass
   await asyncio.sleep(.05)
 raise RuntimeError('startup failed')
async def main():
 with tempfile.TemporaryDirectory() as folder:
  p=await start(str(Path(folder)/'rooms.db'))
  try:
   async with aiohttp.ClientSession() as c:
    base='http://127.0.0.1:18085'
    seat=await (await c.post(base+'/api/rooms',json={'name':'Recovery B'})).json()
    a=await c.ws_connect(base+'/ws');await a.send_json({'type':'join',**seat});await a.receive_json();await state(a)
    b=await c.ws_connect(base+'/ws');await b.send_json({'type':'join','room':seat['room'],'name':'Recovery W'});welcome=await b.receive_json();bt=welcome['token'];await state(b)
    await a.send_json({'type':'move','index':84});d=await state(b)
    while d['moves']!=1:d=await state(b)
    p.kill();await p.wait();await a.close();await b.close()
    await asyncio.sleep(1)
    p=await start(str(Path(folder)/'rooms.db'))
    a=await c.ws_connect(base+'/ws');await a.send_json({'type':'join',**seat});await a.receive_json();d=await state(a)
    assert d['clock']['recovering'] and d['board'][84]==1 and d['moves']==1,d
    frozen=d['clock']['remaining'];print('Real process killed and restarted; board/token recovered; one seat waiting with frozen clocks',flush=True)
    await asyncio.sleep(31)
    # A watch join requests a fresh server state without changing seats.
    watch=await c.ws_connect(base+'/ws');await watch.send_json({'type':'join','room':seat['room'],'mode':'watch'});await watch.receive_json();d=await state(watch)
    assert d['status']=='playing' and d['clock']['remaining']==frozen,d
    b=await c.ws_connect(base+'/ws');await b.send_json({'type':'join','room':seat['room'],'token':bt});await b.receive_json();d=await state(b)
    assert not d['clock']['recovering'] and d['status']=='playing',d
    await b.send_json({'type':'move','index':85});d=await state(b)
    while d['moves']!=2:d=await state(b)
    assert d['board'][85]==-1
    print(json.dumps({'passed':True,'waiting_seconds':31,'moves_after_resume':d['moves'],'remaining':d['clock']['remaining']}),flush=True)
    await a.close();await b.close();await watch.close()
  finally:
   if p.returncode is None:p.terminate();await p.wait()
asyncio.run(main())
