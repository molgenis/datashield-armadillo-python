import uuid

import pytest

from datashield_armadillo.impl import ArmadilloDSError

pytestmark = pytest.mark.integration


def test_uploaded_table_is_listed(conn, table):
    assert table in conn.list_tables()
    assert conn.has_table(table)
    assert not conn.has_table(f"{table}_missing")


def test_assigned_table_can_be_listed_and_removed(conn, table):
    conn.assign_table("removable", table, asynchronous=False)
    assert "removable" in conn.list_symbols()
    conn.rm_symbol("removable")
    assert "removable" not in conn.list_symbols()


def test_asynchronous_assign_completes(conn, table):
    result = conn.assign_table("D", table, variables=["age", "score"])
    assert result.fetch() is None
    assert result.is_completed()
    assert "D" in conn.list_symbols()


def test_selected_profile_is_current(conn, profile):
    profiles = conn.list_profiles()
    assert profiles["current"] == profile
    assert profile in profiles["available"]


def test_aggregate_methods_name_their_package(conn):
    methods = {method["name"]: method for method in conn.list_methods("aggregate")}
    assert methods["meanDS"]["pkg"] == "dsBase"
    assert methods["meanDS"]["version"]


def test_dsbase_is_listed_as_package(conn):
    assert "dsBase" in [package["pkg"] for package in conn.list_packages()]


def test_workspace_can_be_saved_and_removed(conn):
    name = f"pytest-{uuid.uuid4().hex[:10]}"
    conn.save_workspace(name)
    assert name in [workspace["name"] for workspace in conn.list_workspaces()]
    conn.rm_workspace(name)
    assert name not in [workspace["name"] for workspace in conn.list_workspaces()]


def test_failed_aggregate_reports_r_error(conn):
    result = conn.aggregate("meanDS(no_such_symbol$x)")
    with pytest.raises(ArmadilloDSError, match="failed on armadillo: Error : object 'no_such_symbol' not found$"):
        result.fetch()


def test_keep_alive_leaves_last_result_available(conn, table):
    conn.assign_table("D", table, asynchronous=False)
    result = conn.aggregate("dimDS('D')")
    conn.keep_alive()
    assert result.fetch() is not None
