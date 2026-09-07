"""JWKS fetching + in-process key cache.

Keys are fetched over httpx (async, no blocking IO) and cached with a TTL;
an unknown `kid` triggers a refresh, rate-limited so a flood of bogus kids
cannot hammer the issuer's endpoint. The transport is injectable for tests
(`tests/fake_jwks.py` fakes the wire, mirroring `tests/fake_openai.py`).
"""

import time

import httpx
import jwt

# How often an unknown kid may force a refresh, regardless of key-cache TTL:
# fast enough to pick up rotations, slow enough to blunt fetch-amplification.
_UNKNOWN_KID_REFRESH_SECONDS = 30.0


class JwksUnavailableError(Exception):
    """The JWKS endpoint could not be reached or answered unusably."""


class JwksClient:
    def __init__(
        self,
        domain: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        cache_seconds: float = 600.0,
    ) -> None:
        self._url = f"https://{domain}/.well-known/jwks.json"
        self._http = http_client if http_client is not None else httpx.AsyncClient()
        self._owns_client = http_client is None
        self._cache_seconds = cache_seconds
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = float("-inf")

    async def aclose(self) -> None:
        # Caller-owned wires (tests) are closed by their owner, like the LLM client.
        if self._owns_client:
            await self._http.aclose()

    async def get_key(self, kid: str) -> jwt.PyJWK | None:
        """The key for `kid`, or None when the issuer does not know it.

        Fetches on first use and after the cache expires; an unknown kid
        forces a refresh (rate-limited) so a freshly rotated key verifies
        within seconds instead of waiting out the cache.
        """
        expired = time.monotonic() - self._fetched_at > self._cache_seconds
        unknown_kid_refresh = (
            kid not in self._keys
            and time.monotonic() - self._fetched_at > _UNKNOWN_KID_REFRESH_SECONDS
        )
        if expired or unknown_kid_refresh:
            await self._fetch()
        return self._keys.get(kid)

    async def _fetch(self) -> None:
        try:
            response = await self._http.get(self._url)
            response.raise_for_status()
            entries = response.json()["keys"]
            keys = {
                entry["kid"]: jwt.PyJWK(entry)
                for entry in entries
                if entry.get("kid") and entry.get("use", "sig") == "sig"
            }
        except (httpx.HTTPError, jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise JwksUnavailableError(f"jwks fetch failed url={self._url}") from exc
        self._keys = keys
        self._fetched_at = time.monotonic()
