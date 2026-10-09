import pytest
import responses
from datashield.interface import DSLoginInfo
from responses import matchers

from datashield_armadillo import ArmadilloDriver, impl
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


def connect_with_session():
    conn = connect()
    responses.post(f"{URL}/select-profile", status=204)
    return conn


def last_command(status, with_result=True, message=None):
    return {"expression": "meanDS(D$age)", "status": status, "withResult": with_result, "message": message}


@responses.activate
def test_assign_table_loads_table_and_starts_session():
    conn = connect_with_session()
    params = {"symbol": "D", "table": "project/folder/table", "variables": "age,sex", "async": "true"}
    load = responses.post(f"{URL}/load-table", status=201, match=[matchers.query_param_matcher(params)])
    conn.assign_table("D", "project/folder/table", variables=["age", "sex"], missings=True, id_name="id")
    assert load.call_count == 1
    assert conn.has_session()


@responses.activate
def test_assign_resource_loads_resource():
    conn = connect_with_session()
    params = {"symbol": "res", "resource": "project/folder/resource", "async": "true"}
    load = responses.post(f"{URL}/load-resource", status=201, match=[matchers.query_param_matcher(params)])
    conn.assign_resource("res", "project/folder/resource")
    assert load.call_count == 1


@responses.activate
def test_assign_expr_posts_expression():
    conn = connect_with_session()
    assign = responses.post(f"{URL}/symbols/x", status=201, match=[matchers.body_matcher("c(1, 2)")])
    conn.assign_expr("x", "c(1, 2)")
    assert assign.call_count == 1


@responses.activate
def test_assign_result_has_no_value():
    conn = connect_with_session()
    responses.post(f"{URL}/symbols/x", status=201)
    responses.get(f"{URL}/lastcommand", json=last_command("COMPLETED", with_result=False))
    result = conn.assign_expr("x", "c(1, 2)")
    assert result.is_completed()
    assert result.fetch() is None


@responses.activate
def test_aggregate_asks_for_json():
    conn = connect_with_session()
    responses.post(f"{URL}/execute", status=201)
    conn.aggregate("meanDS(D$age)")
    request = responses.calls[-1].request
    assert request.headers["Accept"] == "application/json"
    assert request.body == b"meanDS(D$age)"


@responses.activate
def test_aggregate_result_is_fetched_once_completed():
    conn = connect_with_session()
    responses.post(f"{URL}/execute", status=201)
    responses.get(f"{URL}/lastcommand", json=last_command("IN_PROGRESS"))
    responses.get(f"{URL}/lastcommand", json=last_command("COMPLETED"))
    responses.get(f"{URL}/lastresult", json={"EstimatedMean": 36.6})
    result = conn.aggregate("meanDS(D$age)")
    assert not result.is_completed()
    assert result.is_completed()
    assert result.fetch() == {"EstimatedMean": 36.6}
    assert responses.calls[-1].request.headers["Accept"] == "application/json"


@responses.activate
def test_fetch_waits_for_command_to_finish(monkeypatch):
    monkeypatch.setattr(impl, "POLL_INTERVAL_SECONDS", 0)
    conn = connect_with_session()
    responses.post(f"{URL}/execute", status=201)
    responses.get(f"{URL}/lastcommand", json=last_command("PENDING"))
    responses.get(f"{URL}/lastcommand", json=last_command("IN_PROGRESS"))
    responses.get(f"{URL}/lastcommand", json=last_command("COMPLETED"))
    responses.get(f"{URL}/lastresult", json=[1, 2, 3])
    assert conn.aggregate("meanDS(D$age)").fetch() == [1, 2, 3]


@responses.activate
def test_synchronous_aggregate_returns_result_without_polling():
    conn = connect_with_session()
    params = {"async": "false"}
    responses.post(f"{URL}/execute", json={"EstimatedMean": 36.6}, match=[matchers.query_param_matcher(params)])
    result = conn.aggregate("meanDS(D$age)", asynchronous=False)
    assert result.is_completed()
    assert result.fetch() == {"EstimatedMean": 36.6}


@responses.activate
def test_fetch_raises_message_of_failed_command():
    conn = connect_with_session()
    responses.post(f"{URL}/execute", status=201)
    message = '500 Internal Server Error: "{"status":"BAD_REQUEST","message":"object not found"}"'
    responses.get(f"{URL}/lastcommand", json=last_command("FAILED", message=message))
    result = conn.aggregate("meanDS(D$age)")
    with pytest.raises(ArmadilloDSError, match=r"Command 'meanDS\(D\$age\)' failed on server1: object not found"):
        result.fetch()


@responses.activate
def test_synchronous_failure_raises_message_of_failed_command():
    conn = connect_with_session()
    responses.post(f"{URL}/execute", status=500)
    responses.get(f"{URL}/lastcommand", json=last_command("FAILED", message="object not found"))
    with pytest.raises(ArmadilloDSError, match="failed on server1: object not found"):
        conn.aggregate("meanDS(D$age)", asynchronous=False)


@responses.activate
def test_assign_table_raises_server_message_for_unknown_table():
    conn = connect_with_session()
    responses.post(f"{URL}/load-table", status=404, json={"message": "Project 'project' has no object 'x'"})
    with pytest.raises(ArmadilloDSError, match="has no object") as raised:
        conn.assign_table("D", "project/folder/x")
    assert raised.value.code == 404


def ds_method(name, package, version):
    return {"name": name, "function": f"{package}::{name}", "package": package, "version": version}


@responses.activate
def test_list_symbols_starts_session():
    conn = connect_with_session()
    responses.get(f"{URL}/symbols", json=["D", "x"])
    assert conn.list_symbols() == ["D", "x"]
    assert conn.has_session()


@responses.activate
def test_rm_symbol():
    conn = connect_with_session()
    remove = responses.delete(f"{URL}/symbols/D", status=200)
    conn.rm_symbol("D")
    assert remove.call_count == 1


@responses.activate
def test_list_profiles():
    conn = connect()
    profiles = {"available": ["default", "xenon"], "current": "default"}
    responses.get(f"{URL}/profiles", json=profiles)
    assert conn.list_profiles() == profiles


@responses.activate
def test_list_methods():
    conn = connect()
    responses.get(f"{URL}/methods/assign", json=[ds_method("asNumericDS", "dsBase", "6.3.5")])
    assert conn.list_methods("assign") == [
        {"name": "asNumericDS", "class": "func", "value": "dsBase::asNumericDS", "pkg": "dsBase", "version": "6.3.5"}
    ]


@responses.activate
def test_list_packages_lists_each_method_package_once():
    conn = connect()
    aggregate = [ds_method("meanDS", "dsBase", "6.3.5"), ds_method("filterDS", "dsTidyverse", "1.2.1")]
    responses.get(f"{URL}/methods/aggregate", json=aggregate)
    responses.get(f"{URL}/methods/assign", json=[ds_method("asNumericDS", "dsBase", "6.3.5")])
    assert conn.list_packages() == [
        {"pkg": "dsBase", "version": "6.3.5"},
        {"pkg": "dsTidyverse", "version": "1.2.1"},
    ]


@responses.activate
def test_list_workspaces():
    conn = connect()
    workspaces = [{"name": "server1:saved", "lastModified": "2026-10-09T10:00:00Z", "size": 1024}]
    responses.get(f"{URL}/workspaces", json=workspaces)
    assert conn.list_workspaces() == workspaces


@responses.activate
def test_save_workspace():
    conn = connect_with_session()
    save = responses.post(f"{URL}/workspaces/server1%3Asaved", status=201)
    conn.save_workspace("server1:saved")
    assert save.call_count == 1


@responses.activate
def test_restore_workspace_starts_session():
    conn = connect_with_session()
    restore = responses.post(
        f"{URL}/load-workspace", status=200, match=[matchers.query_param_matcher({"id": "server1:saved"})]
    )
    conn.restore_workspace("server1:saved")
    assert restore.call_count == 1
    assert conn.has_session()


@responses.activate
def test_rm_workspace_ignores_missing_workspace():
    conn = connect()
    responses.delete(f"{URL}/workspaces/gone", status=404)
    conn.rm_workspace("gone")


@responses.activate
def test_rm_workspace_raises_other_errors():
    conn = connect()
    responses.delete(f"{URL}/workspaces/saved", status=500, json={"message": "storage unavailable"})
    with pytest.raises(ArmadilloDSError, match="storage unavailable"):
        conn.rm_workspace("saved")


@responses.activate
def test_all_operations_are_asynchronous():
    assert all(connect().is_async().values())


@responses.activate
def test_keep_alive_does_not_touch_the_r_session():
    conn = connect()
    info = responses.get(f"{URL}/actuator/info", json={})
    conn.keep_alive()
    assert info.call_count == 1
    assert not conn.has_session()


@responses.activate
def test_keep_alive_ignores_failures():
    conn = connect()
    conn.keep_alive()
