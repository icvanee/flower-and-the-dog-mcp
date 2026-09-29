"""
OAuth 2.1-autorisatieserver voor één gebruiker (Iwan).

De MCP SDK levert de endpoints (metadata, /register, /authorize, /token, /revoke)
en de PKCE-controle; dit bestand levert alleen de opslag en de inlogstap.
claude.ai registreert zich via DCR, stuurt de browser naar /authorize, en wij
laten een wachtwoordpagina zien (/login). Na het juiste wachtwoord gaat de
browser terug naar claude.ai met een authorization code.

Tokens worden alleen als SHA-256-hash opgeslagen in SQLite, zodat een gelekt
databasebestand geen bruikbare tokens bevat.
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

ACCESS_TOKEN_TTL = 60 * 60  # 1 uur
REFRESH_TOKEN_TTL = 90 * 24 * 60 * 60  # 90 dagen, roteert bij elk gebruik
AUTH_CODE_TTL = 5 * 60
LOGIN_REQUEST_TTL = 10 * 60


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SingleUserOAuthProvider:
    def __init__(self, db_path: Path, password: str, issuer_url: str, allowed_redirect_hosts: list[str]):
        if not password:
            raise ValueError("MCP_LOGIN_PASSWORD is niet ingesteld")
        self.password = password
        self.issuer_url = issuer_url.rstrip("/")
        self.allowed_redirect_hosts = allowed_redirect_hosts
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS oauth ("
            " kind TEXT NOT NULL, key TEXT NOT NULL, client_id TEXT,"
            " data TEXT NOT NULL, expires_at REAL,"
            " PRIMARY KEY (kind, key))"
        )
        self.db.commit()

    # ─── Opslag ────────────────────────────────────────────────────────────────

    def _put(self, kind: str, key: str, data: str, client_id: str | None = None, expires_at: float | None = None):
        self.db.execute(
            "INSERT OR REPLACE INTO oauth (kind, key, client_id, data, expires_at) VALUES (?, ?, ?, ?, ?)",
            (kind, key, client_id, data, expires_at),
        )
        self.db.commit()

    def _get(self, kind: str, key: str) -> str | None:
        row = self.db.execute(
            "SELECT data FROM oauth WHERE kind = ? AND key = ? AND (expires_at IS NULL OR expires_at > ?)",
            (kind, key, time.time()),
        ).fetchone()
        return row[0] if row else None

    def _delete(self, kind: str, key: str):
        self.db.execute("DELETE FROM oauth WHERE kind = ? AND key = ?", (kind, key))
        self.db.commit()

    def _purge_expired(self):
        self.db.execute("DELETE FROM oauth WHERE expires_at IS NOT NULL AND expires_at < ?", (time.time(),))
        self.db.commit()

    # ─── Clients (DCR) ─────────────────────────────────────────────────────────

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = self._get("client", client_id)
        return OAuthClientInformationFull.model_validate_json(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        for uri in client_info.redirect_uris or []:
            if urlparse(str(uri)).hostname not in self.allowed_redirect_hosts:
                raise RegistrationError("invalid_redirect_uri", f"Redirect naar {uri} is niet toegestaan")
        self._put("client", client_info.client_id, client_info.model_dump_json())

    # ─── Autorisatie: via de wachtwoordpagina ──────────────────────────────────

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        self._purge_expired()
        request_id = secrets.token_urlsafe(32)
        pending = {"client_id": client.client_id, "params": params.model_dump(mode="json")}
        self._put("login", request_id, json.dumps(pending), client.client_id, time.time() + LOGIN_REQUEST_TTL)
        return f"{self.issuer_url}/login?request={request_id}"

    def login_request_exists(self, request_id: str) -> bool:
        return self._get("login", request_id) is not None

    def complete_login(self, request_id: str, password: str) -> str | None:
        """Controleert het wachtwoord en geeft de redirect-URL terug, of None bij een fout wachtwoord."""
        data = self._get("login", request_id)
        if data is None:
            raise AuthorizeError("invalid_request", "Inlogverzoek verlopen, probeer opnieuw te verbinden")
        if not hmac.compare_digest(password.encode(), self.password.encode()):
            return None
        self._delete("login", request_id)

        pending = json.loads(data)
        params = AuthorizationParams.model_validate(pending["params"])
        code = AuthorizationCode(
            code=secrets.token_urlsafe(32),
            scopes=params.scopes or [],
            expires_at=time.time() + AUTH_CODE_TTL,
            client_id=pending["client_id"],
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            subject="iwan",
        )
        self._put("code", _hash(code.code), code.model_dump_json(), code.client_id, code.expires_at)
        return construct_redirect_uri(str(params.redirect_uri), code=code.code, state=params.state)

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        data = self._get("code", _hash(authorization_code))
        return AuthorizationCode.model_validate_json(data) if data else None

    # ─── Tokens ────────────────────────────────────────────────────────────────

    def _issue_tokens(self, client_id: str, scopes: list[str], resource: str | None, subject: str | None) -> OAuthToken:
        now = int(time.time())
        access = AccessToken(
            token=secrets.token_urlsafe(32),
            client_id=client_id,
            scopes=scopes,
            expires_at=now + ACCESS_TOKEN_TTL,
            resource=resource,
            subject=subject,
        )
        refresh = RefreshToken(
            token=secrets.token_urlsafe(32),
            client_id=client_id,
            scopes=scopes,
            expires_at=now + REFRESH_TOKEN_TTL,
            resource=resource,
            subject=subject,
        )
        self._put("access", _hash(access.token), access.model_dump_json(), client_id, access.expires_at)
        self._put("refresh", _hash(refresh.token), refresh.model_dump_json(), client_id, refresh.expires_at)
        return OAuthToken(
            access_token=access.token,
            expires_in=ACCESS_TOKEN_TTL,
            scope=" ".join(scopes) or None,
            refresh_token=refresh.token,
        )

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        self._delete("code", _hash(authorization_code.code))
        return self._issue_tokens(
            authorization_code.client_id,
            authorization_code.scopes,
            authorization_code.resource,
            authorization_code.subject,
        )

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str):
        data = self._get("refresh", _hash(refresh_token))
        return RefreshToken.model_validate_json(data) if data else None

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        self._delete("refresh", _hash(refresh_token.token))
        return self._issue_tokens(
            refresh_token.client_id,
            scopes or refresh_token.scopes,
            refresh_token.resource,
            refresh_token.subject,
        )

    async def load_access_token(self, token: str):
        data = self._get("access", _hash(token))
        return AccessToken.model_validate_json(data) if data else None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        # Intrekken van één token trekt alle tokens van die client in
        self.db.execute(
            "DELETE FROM oauth WHERE kind IN ('access', 'refresh') AND client_id = ?",
            (token.client_id,),
        )
        self.db.commit()
