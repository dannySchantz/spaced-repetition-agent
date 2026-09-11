import os

import httpx

from recall.config import server_url


class Client:
    def __init__(self, transport=None):
        from recall.config import auth_token
        token = auth_token()
        self.url = server_url()
        self.http = httpx.AsyncClient(
            base_url=self.url,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            transport=transport,
            timeout=30,
        )

    async def request(self, method, path, **kwargs):
        response = await self.http.request(method, "/v1/" + path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.http.aclose()
