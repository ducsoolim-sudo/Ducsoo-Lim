import os
import time
import unittest
from unittest.mock import AsyncMock, patch
from aiohttp.test_utils import TestClient, TestServer
import auth
import social_auth as social
import server
from storage import RoomStore


class SocialLogin(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {
            'PUBLIC_ORIGIN':'https://go.example', 'FIREBASE_API_KEY':'public-web-key',
            'FIREBASE_PROJECT_ID':'go-test', 'FIREBASE_AUTH_DOMAIN':'go-test.firebaseapp.com',
            'FIREBASE_AUTH_PROVIDERS':'google,facebook,twitter,apple'})
        self.env.start()
        self.store = RoomStore(path=':memory:', database_url='')
        self.client = TestClient(TestServer(server.make_app(self.store)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.env.stop()

    def claims(self, provider='facebook', subject='123'):
        now = time.time()
        return {'aud':'go-test', 'iss':'https://securetoken.google.com/go-test',
                'sub':'broker-user', 'iat':now, 'exp':now+3600, 'auth_time':now,
                'name':'Tester', 'email_verified':True,
                'firebase':{'sign_in_provider':social.PROVIDERS[provider],
                            'identities':{social.PROVIDERS[provider]:[subject]}}}

    async def sign_in(self, claims=None, nonce=None):
        if nonce is None:
            nonce = (await (await self.client.get('/api/auth/config')).json())['nonce']
        self.client.session.cookie_jar.update_cookies({auth.NONCE:nonce})
        with patch('social_auth.verify_token', AsyncMock(return_value=claims or self.claims())):
            return await self.client.post('/api/auth/social', json={'idToken':'signed', 'nonce':nonce},
                                          headers={'Origin':'https://go.example'})

    async def test_all_providers_create_server_sessions_and_google_keeps_old_id(self):
        for provider in social.PROVIDERS:
            response = await self.sign_in(self.claims(provider))
            self.assertEqual(response.status,200)
            user = (await response.json())['user']
            self.assertEqual(user['id'], '123' if provider=='google' else provider+':123')
            self.assertEqual(user['provider'],provider)
            cookie = response.cookies[auth.COOKIE]
            self.assertTrue(cookie['secure']);self.assertTrue(cookie['httponly'])
            self.assertEqual(cookie['samesite'],'Lax')
            self.assertEqual((await self.store.auth_get('session:'+auth.digest(cookie.value)))['id'],user['id'])

    async def test_wrong_project_issuer_times_subject_and_provider_rejected(self):
        modifications = [{'aud':'other'}, {'iss':'https://evil.test'}, {'exp':0},
                         {'auth_time':time.time()-301}, {'iat':time.time()+100}, {'sub':''},
                         {'firebase':{'sign_in_provider':'password'}}, {'email_verified':False}]
        for change in modifications:
            claims = self.claims('google');claims.update(change)
            self.assertEqual((await self.sign_in(claims)).status,401,change)

    async def test_provider_ids_cannot_collide_or_merge_by_email(self):
        ids=[]
        for provider in social.PROVIDERS:
            claims=self.claims(provider);claims['email']='same@example.test'
            ids.append(social.verified_user(claims,'go-test',list(social.PROVIDERS))['id'])
        self.assertEqual(len(set(ids)),4)
        claims=self.claims();del claims['firebase']['identities']
        self.assertEqual((await self.sign_in(claims)).status,401)

    async def test_nonce_single_use_and_parallel_replay(self):
        import asyncio
        nonce=(await (await self.client.get('/api/auth/config')).json())['nonce']
        self.client.session.cookie_jar.update_cookies({auth.NONCE:nonce})
        async def post():
            return await self.client.post('/api/auth/social',json={'idToken':'signed','nonce':nonce},
                                          headers={'Origin':'https://go.example'})
        with patch('social_auth.verify_token',AsyncMock(return_value=self.claims())):
            responses=await asyncio.gather(post(),post())
        self.assertEqual(sorted(r.status for r in responses),[200,401])

    async def test_disabled_and_cross_origin_do_not_verify(self):
        with patch('social_auth.verify_token', AsyncMock()) as verify:
            response=await self.client.post('/api/auth/social',json={'idToken':'x'},headers={'Origin':'https://evil.test'})
            self.assertEqual(response.status,403)
            with patch.dict(os.environ,{'FIREBASE_API_KEY':''}):
                data=await (await self.client.get('/api/auth/config')).json()
                self.assertIsNone(data['social'])
                response=await self.client.post('/api/auth/social',headers={'Origin':'https://go.example'})
                self.assertEqual(response.status,503)
            verify.assert_not_awaited()

    async def test_bad_nonce_and_bad_signature_create_no_session(self):
        with patch('social_auth.verify_token',AsyncMock(side_effect=ValueError('signature'))):
            nonce=(await (await self.client.get('/api/auth/config')).json())['nonce']
            self.client.session.cookie_jar.update_cookies({auth.NONCE:nonce})
            for supplied in ('wrong',nonce):
                response=await self.client.post('/api/auth/social',json={'idToken':'forged','nonce':supplied},headers={'Origin':'https://go.example'})
                self.assertEqual(response.status,401)
                self.assertNotIn(auth.COOKIE,response.cookies)

    async def test_unlisted_provider_and_tenant_rejected(self):
        with patch.dict(os.environ,{'FIREBASE_AUTH_PROVIDERS':'google'}):
            self.assertEqual((await self.sign_in(self.claims('apple'))).status,401)
        claims=self.claims();claims['firebase']['tenant']='other-tenant'
        self.assertEqual((await self.sign_in(claims)).status,401)

    async def test_real_signature_verifier_checks_project_and_tampering(self):
        import json
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        from types import SimpleNamespace
        from google.auth import crypt, jwt
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        public_pem = private.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        signer = crypt.RSASigner.from_string(private_pem, key_id='test-key')
        claims = self.claims()
        claims['iat'] = int(time.time()) - 1
        token = jwt.encode(signer, claims).decode()
        transport = lambda *args, **kwargs: SimpleNamespace(
            status=200, data=json.dumps({'test-key': public_pem.decode()}).encode())
        with patch('google.auth.transport.requests.Request', return_value=transport):
            verified = await social.verify_token(token, 'go-test')
            self.assertEqual(verified['sub'], 'broker-user')
            with self.assertRaises(ValueError):
                await social.verify_token(token, 'wrong-project')
            parts = token.split('.')
            parts[2] = ('A' if parts[2][0] != 'A' else 'B') + parts[2][1:]
            with self.assertRaises(ValueError):
                await social.verify_token('.'.join(parts), 'go-test')
