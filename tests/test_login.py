import stat

import pytest
import responses
import yaml

from datashield_armadillo import login

URL = "https://armadillo.example.org"


class FakeAuthClient:
    created_with = None

    def __init__(self, auth_server, client_id, scopes):
        FakeAuthClient.created_with = {"auth_server": auth_server, "client_id": client_id, "scopes": scopes}

    def device_flow_auth(self):
        return {"access_token": "new-token", "refresh_token": "refresh"}


@pytest.fixture
def token_request(monkeypatch):
    monkeypatch.setattr(login, "request_access_token", lambda url: f"token-for-{url}")


def read_servers(path):
    return yaml.safe_load(path.read_text())["servers"]


def test_login_adds_new_server(tmp_path, token_request):
    config = tmp_path / "datashield" / "config.yaml"
    login.main(["armadillo1", "--url", URL, "--config", str(config)])
    assert read_servers(config) == [
        {"name": "armadillo1", "url": URL, "driver": login.DRIVER, "token": f"token-for-{URL}"}
    ]


def test_login_updates_token_of_listed_server(tmp_path, token_request):
    config = tmp_path / "config.yaml"
    opal = {"name": "opal1", "url": "https://opal.example.org", "user": "dsuser", "password": "secret"}
    armadillo = {"name": "armadillo1", "url": URL, "profile": "xenon", "driver": login.DRIVER, "token": "old"}
    config.write_text(yaml.safe_dump({"servers": [opal, armadillo]}))
    login.main(["armadillo1", "--config", str(config)])
    assert read_servers(config) == [opal, {**armadillo, "token": f"token-for-{URL}"}]


def test_login_fails_for_unlisted_server_without_url(tmp_path, token_request):
    config = tmp_path / "config.yaml"
    with pytest.raises(SystemExit, match="give its address with --url"):
        login.main(["armadillo1", "--config", str(config)])
    assert not config.exists()


def test_config_is_readable_by_owner_only(tmp_path, token_request):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"servers": []}))
    config.chmod(0o644)
    login.main(["armadillo1", "--url", URL, "--config", str(config)])
    assert stat.S_IMODE(config.stat().st_mode) == 0o600


@responses.activate
def test_access_token_is_requested_with_server_auth_settings(monkeypatch):
    monkeypatch.setattr(login, "MolgenisAuthClient", FakeAuthClient)
    auth = {"issuerUri": "https://auth.example.org", "clientId": "client-1"}
    responses.get(f"{URL}/actuator/info", json={"auth": auth})
    assert login.request_access_token(f"{URL}/") == "new-token"
    assert FakeAuthClient.created_with == {
        "auth_server": "https://auth.example.org",
        "client_id": "client-1",
        "scopes": "openid offline_access",
    }
