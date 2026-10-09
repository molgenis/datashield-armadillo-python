import pytest
import responses
from datashield.interface import DSLoginInfo
from responses import matchers

from datashield_armadillo import ArmadilloDriver
from datashield_armadillo.impl import ArmadilloDSError

URL = "https://armadillo.example.org"
DRIVER = "datashield_armadillo.ArmadilloDriver"


def connect(**credentials):
    credentials = credentials or {"token": "abc"}
    responses.get(f"{URL}/my/principal", json={})
    return ArmadilloDriver.new_connection(DSLoginInfo(name="server1", url=URL, driver=DRIVER, **credentials))


@responses.activate
def test_token_is_sent_as_bearer():
    connect(token="abc")
    assert responses.calls[0].request.headers["Authorization"] == "Bearer abc"


@responses.activate
def test_user_and_password_are_sent_as_basic_auth():
    connect(user="admin", password="admin")
    assert responses.calls[0].request.headers["Authorization"].startswith("Basic ")


@responses.activate
def test_connection_fails_when_not_authenticated():
    responses.get(f"{URL}/my/principal", status=401)
    with pytest.raises(ArmadilloDSError, match="Failed to authenticate"):
        ArmadilloDriver.new_connection(DSLoginInfo(name="server1", url=URL, driver=DRIVER, token="expired"))


@responses.activate
def test_list_tables():
    conn = connect()
    responses.get(f"{URL}/tables", json=["project/folder/table"])
    assert conn.list_tables() == ["project/folder/table"]


@responses.activate
def test_has_table():
    conn = connect()
    responses.head(f"{URL}/tables/project/folder/table", status=200)
    responses.head(f"{URL}/tables/project/folder/missing", status=404)
    assert conn.has_table("project/folder/table")
    assert not conn.has_table("project/folder/missing")


@responses.activate
def test_list_resources():
    conn = connect()
    responses.get(f"{URL}/resources", json=["project/folder/resource"])
    assert conn.list_resources() == ["project/folder/resource"]


@responses.activate
def test_has_resource():
    conn = connect()
    responses.head(f"{URL}/resources/project/folder/resource", status=200)
    responses.head(f"{URL}/resources/project/folder/missing", status=404)
    assert conn.has_resource("project/folder/resource")
    assert not conn.has_resource("project/folder/missing")


@responses.activate
def test_variable_discovery_is_not_supported():
    conn = connect()
    with pytest.raises(ArmadilloDSError):
        conn.list_table_variables("project/folder/table")
    with pytest.raises(ArmadilloDSError):
        conn.search_variables("age")
    assert conn.list_taxonomies() == []


@responses.activate
def test_start_session_selects_profile_once():
    conn = connect()
    select = responses.post(f"{URL}/select-profile", status=204, match=[matchers.body_matcher("default")])
    assert not conn.has_session()
    session = conn.start_session()
    assert conn.start_session() is session
    assert select.call_count == 1
    assert conn.is_session_started()
    assert session.is_ready()


@responses.activate
def test_start_session_fails_for_unknown_profile():
    conn = connect()
    responses.post(f"{URL}/select-profile", status=404)
    with pytest.raises(ArmadilloDSError, match="Profile not found: 'default'"):
        conn.start_session()
    assert not conn.has_session()


@responses.activate
def test_start_session_restores_workspace():
    responses.get(f"{URL}/my/principal", json={})
    info = DSLoginInfo(name="server1", url=URL, driver=DRIVER, token="abc")
    conn = ArmadilloDriver.new_connection(info, restore="saved")
    responses.post(f"{URL}/select-profile", status=204)
    restore = responses.post(f"{URL}/load-workspace", status=204, match=[matchers.query_param_matcher({"id": "saved"})])
    conn.start_session()
    assert restore.call_count == 1


@responses.activate
def test_get_session_fails_before_start():
    conn = connect()
    with pytest.raises(ArmadilloDSError):
        conn.get_session()


@responses.activate
def test_error_carries_server_message_and_code():
    conn = connect()
    responses.get(f"{URL}/tables", status=500, json={"message": "storage unavailable"})
    with pytest.raises(ArmadilloDSError) as raised:
        conn.list_tables()
    assert raised.value.message == "storage unavailable"
    assert raised.value.is_server_error()
    assert not raised.value.is_client_error()


@responses.activate
def test_disconnect_logs_out_and_ends_session():
    conn = connect()
    responses.post(f"{URL}/select-profile", status=204)
    logout = responses.post(f"{URL}/logout", status=200)
    session = conn.start_session()
    conn.disconnect()
    assert logout.call_count == 1
    assert session.is_terminated()
