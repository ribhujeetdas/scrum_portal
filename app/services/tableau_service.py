# ===== FILE: services/tableau_service.py =====
from __future__ import annotations
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import quote


class TableauServiceError(Exception):
    pass


class TableauService:
    """
    Tableau REST API (PAT) flow:
      1) POST /api/{version}/auth/signin using personalAccessTokenName/Secret + site.contentUrl
      2) GET  /api/{version}/sites/{siteId}/users/{userId} to fetch current user details
      3) POST /api/{version}/auth/signout (best-effort)
    """

    def __init__(
        self,
        base_url: str,
        api_version: str = "3.7",
        site_content_url: str = "",
        timeout_seconds: int = 20,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_version = (api_version or "3.7").strip()
        self.site_content_url = (site_content_url or "").strip()
        self.timeout = timeout_seconds

        if not self.base_url:
            raise ValueError("TABLEAU_BASE_URL is missing.")

        self._session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retries))
        self._session.mount("http://", HTTPAdapter(max_retries=retries))

    def _api(self, path: str) -> str:
        return f"{self.base_url}/api/{self.api_version}{path}"

    @staticmethod
    def _headers_json() -> dict:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    @staticmethod
    def _headers_auth(token: str) -> dict:
        return {"Accept": "application/json", "X-Tableau-Auth": token}

    def sign_in_with_pat(self, pat_name: str, pat_secret: str) -> dict:
        url = self._api("/auth/signin")
        payload = {
            "credentials": {
                "personalAccessTokenName": pat_name,
                "personalAccessTokenSecret": pat_secret,
                "site": {"contentUrl": self.site_content_url},  # default => ""
            }
        }

        try:
            resp = self._session.post(
                url, headers=self._headers_json(), json=payload, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise TableauServiceError(
                f"Network error calling Tableau sign-in: {exc}") from exc

        if resp.status_code == 401:
            raise TableauServiceError(
                "Unauthorized (401). Check Tableau PAT name/secret.")
        if resp.status_code == 403:
            raise TableauServiceError(
                "Forbidden (403). Tableau PAT lacks access.")
        if resp.status_code >= 400:
            raise TableauServiceError(
                f"Tableau sign-in error: {resp.status_code} {resp.text[:200]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise TableauServiceError(
                "Invalid JSON returned by Tableau sign-in.") from exc

        creds = (data.get("credentials") or {})
        token = creds.get("token")
        site = creds.get("site") or {}
        user = creds.get("user") or {}

        site_id = site.get("id")
        user_id = user.get("id")
        content_url = site.get("contentUrl", self.site_content_url)

        if not token or not site_id or not user_id:
            raise TableauServiceError(
                "Tableau sign-in response missing token/site.id/user.id.")

        return {
            "token": token,
            "site_id": str(site_id),
            "user_id": str(user_id),
            "content_url": str(content_url or ""),
        }

    def get_user_details(self, token: str, site_id: str, user_id: str) -> dict:
        url = self._api(f"/sites/{site_id}/users/{user_id}")
        try:
            resp = self._session.get(
                url, headers=self._headers_auth(token), timeout=self.timeout)
        except requests.RequestException as exc:
            raise TableauServiceError(
                f"Network error fetching Tableau user details: {exc}") from exc

        if resp.status_code == 401:
            raise TableauServiceError(
                "Unauthorized (401) while fetching Tableau user details.")
        if resp.status_code == 403:
            raise TableauServiceError(
                "Forbidden (403) while fetching Tableau user details.")
        if resp.status_code >= 400:
            raise TableauServiceError(
                f"Tableau user details error: {resp.status_code} {resp.text[:200]}")

        try:
            return resp.json()
        except ValueError as exc:
            raise TableauServiceError(
                "Invalid JSON returned by Tableau user details endpoint.") from exc

    def sign_out(self, token: str) -> None:
        url = self._api("/auth/signout")
        try:
            self._session.post(url, headers=self._headers_auth(
                token), timeout=self.timeout)
        except Exception:
            return

    @staticmethod
    def _extract_identity(user_details_json: dict) -> dict:
        """
        Expected shape often includes: {"user": {...}}
        We extract:
          - eid: user.name (stored as tableau_eid)
          - email: user.email (or fallbacks)
        """
        u = user_details_json.get(
            "user") or user_details_json.get("users") or {}
        if isinstance(u, dict) and "user" in u and isinstance(u["user"], dict):
            # handle odd nesting
            u = u["user"]

        if not isinstance(u, dict):
            u = {}

        tableau_name = (u.get("name") or u.get("username") or "").strip()
        tableau_email = (u.get("email") or u.get("emailAddress") or "").strip()

        # Some environments (Cloud) use username as email; fallback if email missing
        if not tableau_email and tableau_name and "@" in tableau_name:
            tableau_email = tableau_name

        return {
            "eid": tableau_name,
            "email": tableau_email,
        }

    def validate_pat_and_get_identity(self, pat_name: str, pat_secret: str) -> dict:
        """
        sign-in -> get user -> sign-out -> return normalized identity bundle (no token).
        """
        signin = self.sign_in_with_pat(pat_name, pat_secret)
        token = signin["token"]
        try:
            details = self.get_user_details(
                token, signin["site_id"], signin["user_id"])
            ident = self._extract_identity(details)
        finally:
            self.sign_out(token)

        if not ident.get("eid"):
            raise TableauServiceError(
                "Unable to extract Tableau user 'name' (EID) from Tableau response.")
        if not ident.get("email"):
            raise TableauServiceError(
                "Unable to extract Tableau user email from Tableau response.")

        return {
            "site_id": signin["site_id"],
            "user_id": signin["user_id"],
            "content_url": signin["content_url"],
            "eid": ident["eid"],
            "email": ident["email"],
        }

    def list_custom_views(self, token: str, site_id: str, page_size: int = 1000, page_number: int = 1, filter_expr: str | None = None) -> dict:
        """
        GET /api/{version}/sites/{site_id}/customviews?pageSize=...&filter=...
        """
        qs = f"?pageSize={page_size}&pageNumber={page_number}"
        if filter_expr:
            # keep ':' unescaped because filter expressions use ':'
            qs += f"&filter={quote(filter_expr, safe=':')}"
        url = self._api(f"/sites/{site_id}/customviews{qs}")

        try:
            resp = self._session.get(
                url, headers=self._headers_auth(token), timeout=self.timeout)
        except requests.RequestException as exc:
            raise TableauServiceError(
                f"Network error listing Tableau custom views: {exc}") from exc

        if resp.status_code == 401:
            raise TableauServiceError(
                "Unauthorized (401) while listing Tableau custom views.")
        if resp.status_code == 403:
            raise TableauServiceError(
                "Forbidden (403) while listing Tableau custom views.")
        if resp.status_code >= 400:
            raise TableauServiceError(
                f"List custom views failed: {resp.status_code} {resp.text[:300]}")

        try:
            return resp.json()
        except ValueError as exc:
            raise TableauServiceError(
                "Invalid JSON returned by Tableau custom views list.") from exc

    @staticmethod
    def _extract_custom_view_items(payload: dict) -> list[dict]:
        root = payload.get("customViews") or {}
        items = root.get("customView") or []
        if isinstance(items, dict):
            return [items]
        if isinstance(items, list):
            return items
        return []

    def fetch_custom_view_details_by_id(
        self,
        pat_name: str,
        pat_secret: str,
        site_id: str,
        custom_view_id: str,
    ) -> dict:
        """
        Sign in -> List Custom Views (no 'id' filter because server rejects it) -> find by id -> Sign out.
        """
        signin = self.sign_in_with_pat(pat_name, pat_secret)
        token = signin["token"]

        try:
            page_size = 1000
            page_number = 1

            while True:
                payload = self.list_custom_views(
                    token=token,
                    site_id=site_id,
                    page_size=page_size,
                    page_number=page_number,
                    # IMPORTANT: do not use id:eq filter (our server rejects it)
                    filter_expr=None,
                )

                items = self._extract_custom_view_items(payload)
                for cv in items:
                    if (cv.get("id") or "").strip() == custom_view_id:
                        return cv

                # pagination
                pagination = payload.get("pagination") or {}
                total_available = int(pagination.get("totalAvailable") or 0)
                if total_available <= page_number * page_size:
                    break
                page_number += 1

        finally:
            self.sign_out(token)

        raise TableauServiceError(
            "Custom view not found or not accessible for this user.")

    def query_custom_view_data_csv(self, token: str, site_id: str, custom_view_id: str, max_age_minutes: int = 60) -> bytes:
        """
        GET /api/{version}/sites/{site-id}/customviews/{customview-id}/data?maxAge=60
        Returns raw CSV bytes.
        """
        url = self._api(f"/sites/{site_id}/customviews/{custom_view_id}/data")

        try:
            # Use permissive Accept to avoid 406
            resp = self._session.get(
                url,
                headers={**self._headers_auth(token), "Accept": "*/*"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise TableauServiceError(
                # improve error message
                f"Network error querying custom view data: {exc}") from exc

        if resp.status_code == 401:
            raise TableauServiceError(
                "Unauthorized (401) while querying custom view data.")
        if resp.status_code == 403:
            raise TableauServiceError(
                "Forbidden (403) while querying custom view data.")
        if resp.status_code >= 400:
            raise TableauServiceError(
                f"Query custom view data failed: {resp.status_code} {resp.text[:300]}")

        return resp.content
