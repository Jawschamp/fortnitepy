# -*- coding: utf-8 -*-

"""
MIT License

Copyright (c) 2019 Terbau

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import datetime
import asyncio
import logging
import traceback
import uuid

from .errors import AuthException, HTTPException

log = logging.getLogger(__name__)


class Auth:
    def __init__(self, client):
        self.client = client
        self.device_id = self.client.device_id or uuid.uuid4().hex

    @property
    def launcher_authorization(self):
        return 'bearer {0}'.format(self.launcher_access_token)

    @property
    def authorization(self):
        return 'bearer {0}'.format(self.access_token)

    async def authenticate(self):
        try:
            data = {
                'grant_type': 'password',
                'username': self.client.email,
                'password': self.client.password
            }

            try:
                data = await self.grant_session('LAUNCHER', data=data)
            except HTTPException as exc:
                log.debug('Could not authenticate normally, checking why now.')

                if exc.message_code != 'errors.com.epicgames.common.two_factor_authentication.required':
                    raise HTTPException(exc.response, exc.raw)
                
                log.debug('2fa code required to continue login process. Asking for code now.')

                code = self.client.two_factor_code
                if code is None:
                    code = int(input('Please enter the 2fa code:\n'))

                data = {
                    'grant_type': 'otp',
                    'otp': str(code),
                    'challenge': exc.raw['challenge']
                }
                data = await self.grant_session('LAUNCHER', data=data)
                log.debug('Valid 2fa code entered')

            self.launcher_access_token = data['access_token']
            await self.exchange_code('bearer {0}'.format(self.launcher_access_token))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            traceback.print_exc()
            raise AuthException('Could not authenticate. Error: {}'.format(e))

    async def grant_refresh_token(self, refresh_token):
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        }
        return await self.grant_session('FORTNITE', data=data)

    async def get_exchange_code(self, auth):
        res = await self.client.http.get(
            'https://account-public-service-prod03.ol.epicgames.com/account/api/oauth/exchange',
            auth
        )
        return res.get('code')

    async def exchange_code(self, auth):
        code = await self.get_exchange_code(auth)
        if code is None:
            raise AuthException('Could not get exchange code')

        data = {
            'grant_type': 'exchange_code',
            'token_type': 'eg1',
            'exchange_code': code
        }
        
        data = await self.grant_session('FORTNITE', data=data)
        self._update(data)

    async def grant_session(self, auth, **kwargs):
        headers = {
            'X-Epic-Device-ID': self.device_id
        }
        data = await self.client.http.post(
            'https://account-public-service-prod03.ol.epicgames.com/account/api/oauth/token',
            auth,
            **{**kwargs, 'headers': headers}
        )
        return data

    async def kill_token(self, token):
        await self.client.http.delete(
            'https://account-public-service-prod03.ol.epicgames.com/account/api/' \
            'oauth/sessions/kill/{0}'.format(token),
            self.authorization
        )

    async def kill_other_sessions(self):
        await self.client.http.delete(
            'https://account-public-service-prod03.ol.epicgames.com/account/api/' \
            'oauth/sessions/kill?killType=OTHERS_ACCOUNT_CLIENT_SERVICE',
            self.authorization
        )

    async def get_eula_version(self, account_id):
        res = await self.client.http.get(
            'https://eulatracking-public-service-prod-m.ol.epicgames.com/eulatracking/' \
            'api/public/agreements/fn/account/{0}'.format(account_id),
            self.authorization # MIGHT BE fn auth
        )
        return res['version'] if isinstance(res, dict) else 0

    async def _accept_eula(self, version, account_id):
        await self.client.http.post(
            'https://eulatracking-public-service-prod-m.ol.epicgames.com/eulatracking/' \
            'api/public/agreements/fn/version/{0}/account/{1}/accept?locale=en'.format(
                version, 
                account_id
            ),
            self.authorization # MIGHT BE fn auth
        )

    async def accept_eula(self, account_id):
        version = await self.get_eula_version(account_id)
        if version != 0:
            await self._accept_eula(version, account_id)
            await self._grant_access(account_id)

    async def _grant_access(self, account_id):
        await self.client.http.post(
            'https://fortnite-public-service-prod11.ol.epicgames.com/fortnite/api/' \
            'game/v2/grant_access/{0}'.format(account_id),
            self.authorization
        )

    def _update(self, data):
        self.access_token = data['access_token']
        self.expires_in = data['expires_in']
        self.expires_at = self.client.from_iso(data["expires_at"])
        self.token_type = data['token_type']
        self.refresh_token = data['refresh_token']
        self.refresh_expires = data['refresh_expires']
        self.refresh_expires_at = data['refresh_expires_at']
        self.account_id = data['account_id']
        self.client_id = data['client_id']
        self.internal_client = data['internal_client']
        self.client_service = data['client_service']
        self.app = data['app']
        self.in_app_id = data['in_app_id']
    
    async def schedule_token_refresh(self):
        self.token_timeout = (self.expires_at - datetime.datetime.now()).total_seconds() - 300
        await asyncio.sleep(self.token_timeout)
        await self.do_refresh()

    async def do_refresh(self):
        log.debug('Refreshing session')

        if self.client.user.party is not None:
            await self.client.user.party._leave()

        data = await self.grant_refresh_token(self.refresh_token)
        self.launcher_access_token = data['access_token']
        await self.exchange_code('bearer {}'.format(self.launcher_access_token))

        log.debug('Refreshing xmpp session')
        await self.client.xmpp.close()
        await self.client.xmpp.run()

        await self.client._create_party()
        await self.schedule_token_refresh()
