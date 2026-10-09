"""
DataSHIELD Interface implementation for MOLGENIS Armadillo.
"""

from contextlib import suppress
from urllib.parse import quote

import requests
from datashield.interface import DSConnection, DSDriver, DSError, DSLoginInfo, RSession

REQUEST_TIMEOUT_SECONDS = 300


class ArmadilloDSError(DSError):
    def __init__(self, message: str, code: int | None = None, details: str | None = None):
        super().__init__(message)
        self.code = code
        self.details = details

    def get_error(self) -> dict:
        return {"message": self.message, "code": self.code, "details": self.details}

    def is_client_error(self) -> bool:
        return self.code is None or 400 <= self.code < 500

    def is_server_error(self) -> bool:
        return self.code is not None and self.code >= 500


class ArmadilloRSession(RSession):
    def __init__(self, profile: str):
        self.profile = profile
        self.closed = False

    def is_started(self) -> bool:
        return True

    def is_ready(self) -> bool:
        return not self.closed

    def is_pending(self) -> bool:
        return False

    def is_failed(self) -> bool:
        return False

    def is_terminated(self) -> bool:
        return self.closed

    def get_last_message(self) -> str:
        return f"Profile '{self.profile}' selected"

    def close(self) -> None:
        self.closed = True


class ArmadilloConnection(DSConnection):
    def __init__(
        self, name: str, url: str, http: requests.Session, profile: str = "default", restore: str | None = None
    ):
        self.name = name
        self.url = url.rstrip("/")
        self.http = http
        self.profile = profile
        self.restore = restore
        self.rsession = None

    def get_name(self) -> str:
        return self.name

    def check_user(self) -> bool:
        return self._send("GET", "/my/principal").status_code == 200

    def list_tables(self) -> list:
        return self._send_checked("GET", "/tables").json()

    def has_table(self, name: str) -> bool:
        return self._send("HEAD", f"/tables/{quote(name)}").status_code == 200

    def list_table_variables(self, table: str) -> list:
        raise ArmadilloDSError("Armadillo does not support listing the variables of a table")

    def list_taxonomies(self) -> list:
        return []

    def search_variables(self, query: str) -> dict:
        raise ArmadilloDSError("Armadillo does not support searching variables")

    def list_resources(self) -> list:
        return self._send_checked("GET", "/resources").json()

    def has_resource(self, name: str) -> bool:
        return self._send("HEAD", f"/resources/{quote(name)}").status_code == 200

    def has_session(self) -> bool:
        return self.rsession is not None

    def start_session(self, asynchronous: bool = True) -> RSession:
        if self.rsession is not None:
            return self.rsession
        self._select_profile()
        if self.restore is not None:
            self.restore_workspace(self.restore)
        self.rsession = ArmadilloRSession(self.profile)
        return self.rsession

    def is_session_started(self) -> bool:
        return self.rsession is not None

    def get_session(self) -> RSession:
        if self.rsession is None:
            raise ArmadilloDSError("No R session established. Please start a session first.")
        return self.rsession

    def restore_workspace(self, name: str) -> None:
        self._send_checked("POST", "/load-workspace", params={"id": name})

    def disconnect(self) -> None:
        if self.rsession is not None:
            self.rsession.close()
        with suppress(ArmadilloDSError):
            self._send("POST", "/logout")
        self.http.close()

    def _select_profile(self) -> None:
        response = self._send("POST", "/select-profile", data=self.profile, headers={"Content-Type": "text/plain"})
        if response.status_code == 404:
            raise ArmadilloDSError(f"Profile not found: '{self.profile}'", 404)
        raise_for_error(response)

    def _send(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            return self.http.request(method, self.url + path, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
        except requests.RequestException as e:
            raise ArmadilloDSError(f"Request to {self.name} failed: {e}") from e

    def _send_checked(self, method: str, path: str, **kwargs) -> requests.Response:
        response = self._send(method, path, **kwargs)
        raise_for_error(response)
        return response


class ArmadilloDriver(DSDriver):
    @classmethod
    def new_connection(cls, args: DSLoginInfo, restore: str | None = None) -> DSConnection:
        conn = ArmadilloConnection(args.name, args.url, open_http_session(args), args.profile, restore)
        if not conn.check_user():
            creds = f"user {args.user}" if args.user else "token"
            raise ArmadilloDSError(f"Failed to authenticate on {args.url} with {creds}")
        return conn


def open_http_session(args: DSLoginInfo) -> requests.Session:
    http = requests.Session()
    if args.token:
        http.headers["Authorization"] = f"Bearer {args.token}"
    else:
        http.auth = (args.user, args.password)
    return http


def raise_for_error(response: requests.Response) -> None:
    if not response.ok:
        raise ArmadilloDSError(read_error_message(response), response.status_code, response.text)


def read_error_message(response: requests.Response) -> str:
    with suppress(ValueError, AttributeError):
        message = response.json().get("message")
        if message:
            return message
    return f"HTTP {response.status_code} {response.reason}"
