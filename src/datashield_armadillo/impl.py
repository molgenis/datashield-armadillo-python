"""
DataSHIELD Interface implementation for MOLGENIS Armadillo.
"""

import json
import re
import time
from contextlib import suppress
from urllib.parse import quote

import requests
from datashield.interface import DSConnection, DSDriver, DSError, DSLoginInfo, DSResult, RSession

REQUEST_TIMEOUT_SECONDS = 300
POLL_INTERVAL_SECONDS = 0.1
FINISHED_STATUSES = ("COMPLETED", "FAILED")
TEXT_PLAIN = {"Content-Type": "text/plain"}
ACCEPT_JSON = {"Accept": "application/json"}


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
            self._load_workspace(self.restore)
        self.rsession = ArmadilloRSession(self.profile)
        return self.rsession

    def is_session_started(self) -> bool:
        return self.rsession is not None

    def get_session(self) -> RSession:
        if self.rsession is None:
            raise ArmadilloDSError("No R session established. Please start a session first.")
        return self.rsession

    def assign_table(
        self,
        symbol: str,
        table: str,
        variables: list | None = None,
        missings: bool = False,
        identifiers: str | None = None,
        id_name: str | None = None,
        asynchronous: bool = True,
    ) -> DSResult:
        params = {"symbol": symbol, "table": table}
        if variables is not None:
            params["variables"] = ",".join(variables)
        return self._run_command("/load-table", asynchronous, params=params)

    def assign_resource(self, symbol: str, resource: str, asynchronous: bool = True) -> DSResult:
        return self._run_command("/load-resource", asynchronous, params={"symbol": symbol, "resource": resource})

    def assign_expr(self, symbol: str, expr: str, asynchronous: bool = True) -> DSResult:
        path = f"/symbols/{quote(symbol, safe='')}"
        return self._run_command(path, asynchronous, data=expr.encode("utf-8"), headers=TEXT_PLAIN)

    def aggregate(self, expr: str, asynchronous: bool = True) -> DSResult:
        headers = {**TEXT_PLAIN, **ACCEPT_JSON}
        return self._run_command("/execute", asynchronous, data=expr.encode("utf-8"), headers=headers)

    def read_last_command(self) -> dict:
        return self._send_checked("GET", "/lastcommand").json()

    def read_last_result(self) -> object:
        return read_json_body(self._send_checked("GET", "/lastresult", headers=ACCEPT_JSON))

    def raise_if_command_failed(self, command: dict) -> None:
        if command.get("status") == "FAILED":
            raise ArmadilloDSError(describe_failed_command(command, self.name))

    def list_symbols(self) -> list:
        self.start_session()
        return self._send_checked("GET", "/symbols").json()

    def rm_symbol(self, name: str) -> None:
        self.start_session()
        self._send_checked("DELETE", f"/symbols/{quote(name, safe='')}")

    def list_profiles(self) -> list:
        return self._send_checked("GET", "/profiles").json()

    def list_methods(self, type: str = "aggregate") -> list:
        methods = self._send_checked("GET", f"/methods/{quote(type, safe='')}").json()
        return [describe_method(method) for method in methods]

    def list_packages(self) -> list:
        methods = self.list_methods("aggregate") + self.list_methods("assign")
        versions = {method["pkg"]: method["version"] for method in methods if method["pkg"]}
        return [{"pkg": pkg, "version": version} for pkg, version in sorted(versions.items())]

    def list_workspaces(self) -> list:
        return self._send_checked("GET", "/workspaces").json()

    def save_workspace(self, name: str) -> None:
        self.start_session()
        self._send_checked("POST", f"/workspaces/{quote(name, safe='')}")

    def restore_workspace(self, name: str) -> None:
        self.start_session()
        self._load_workspace(name)

    def rm_workspace(self, name: str) -> None:
        response = self._send("DELETE", f"/workspaces/{quote(name, safe='')}")
        if response.status_code != 404:
            self._raise_for_error(response)

    def is_async(self) -> dict:
        return {"aggregate": True, "assign_table": True, "assign_resource": True, "assign_expr": True}

    def keep_alive(self) -> None:
        with suppress(ArmadilloDSError):
            self._send("GET", "/actuator/info")

    def disconnect(self) -> None:
        if self.rsession is not None:
            self.rsession.close()
        with suppress(ArmadilloDSError):
            self._send("POST", "/logout")
        self.http.close()

    def _run_command(self, path: str, asynchronous: bool, params: dict | None = None, **kwargs) -> DSResult:
        self.start_session()
        query = {**(params or {}), "async": "true" if asynchronous else "false"}
        response = self._send("POST", path, params=query, **kwargs)
        if response.status_code >= 500:
            self.raise_if_command_failed(self.read_last_command())
        self._raise_for_error(response)
        if asynchronous:
            return ArmadilloResult(self, pending=True)
        return ArmadilloResult(self, pending=False, result=read_json_body(response))

    def _load_workspace(self, name: str) -> None:
        self._send_checked("POST", "/load-workspace", params={"id": name})

    def _select_profile(self) -> None:
        response = self._send("POST", "/select-profile", data=self.profile, headers={"Content-Type": "text/plain"})
        if response.status_code == 404:
            raise ArmadilloDSError(f"Profile not found: '{self.profile}'", 404)
        self._raise_for_error(response)

    def _raise_for_error(self, response: requests.Response) -> None:
        if response.status_code == 401:
            raise ArmadilloDSError(describe_login_failure(self.name), 401, response.text)
        raise_for_error(response)

    def _send(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            return self.http.request(method, self.url + path, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
        except requests.RequestException as e:
            raise ArmadilloDSError(f"Request to {self.name} failed: {e}") from e

    def _send_checked(self, method: str, path: str, **kwargs) -> requests.Response:
        response = self._send(method, path, **kwargs)
        self._raise_for_error(response)
        return response


class ArmadilloResult(DSResult):
    def __init__(self, conn: ArmadilloConnection, pending: bool, result: object = None):
        self.conn = conn
        self.pending = pending
        self.result = result

    def is_completed(self) -> bool:
        if not self.pending:
            return True
        return self.conn.read_last_command()["status"] in FINISHED_STATUSES

    def fetch(self) -> object:
        if not self.pending:
            return self.result
        command = self._wait_for_last_command()
        self.conn.raise_if_command_failed(command)
        self.result = self.conn.read_last_result() if command["withResult"] else None
        self.pending = False
        return self.result

    def _wait_for_last_command(self) -> dict:
        while True:
            command = self.conn.read_last_command()
            if command["status"] in FINISHED_STATUSES:
                return command
            time.sleep(POLL_INTERVAL_SECONDS)


class ArmadilloDriver(DSDriver):
    @classmethod
    def new_connection(cls, args: DSLoginInfo, restore: str | None = None) -> DSConnection:
        conn = ArmadilloConnection(args.name, args.url, open_http_session(args), args.profile, restore)
        if not conn.check_user():
            raise ArmadilloDSError(describe_login_failure(args.name), 401)
        return conn


def open_http_session(args: DSLoginInfo) -> requests.Session:
    http = requests.Session()
    if args.token:
        http.headers["Authorization"] = f"Bearer {args.token}"
    else:
        http.auth = (args.user, args.password)
    return http


def describe_login_failure(server: str) -> str:
    return (
        f"Failed to authenticate on {server}. "
        f"If you log in with a token it may have expired: run 'datashield-armadillo-login {server}'"
    )


def raise_for_error(response: requests.Response) -> None:
    if not response.ok:
        raise ArmadilloDSError(read_error_message(response), response.status_code, response.text)


def read_json_body(response: requests.Response) -> object:
    return response.json() if response.content else None


def describe_method(method: dict) -> dict:
    return {
        "name": method.get("name"),
        "class": "func",
        "value": method.get("function"),
        "pkg": method.get("package"),
        "version": method.get("version"),
    }


def describe_failed_command(command: dict, server: str) -> str:
    return f"Command '{command.get('expression')}' failed on {server}: {read_command_message(command)}"


def read_command_message(command: dict) -> str:
    message = command.get("message") or "<no message>"
    embedded = re.search(r"\{.*\}", message, re.DOTALL)
    if embedded:
        with suppress(ValueError, KeyError, TypeError):
            return json.loads(embedded.group())["message"].strip()
    return message


def read_error_message(response: requests.Response) -> str:
    with suppress(ValueError, AttributeError):
        message = response.json().get("message")
        if message:
            return message
    return f"HTTP {response.status_code} {response.reason}"
