import pytest

from .conftest import ROWS, SERVER

pytestmark = pytest.mark.integration

datashield_base = pytest.importorskip("datashield_base")


@pytest.fixture(scope="module")
def stats(session, table):
    session.assign_table("D", table=table)
    return datashield_base.StatsClient(session)


@pytest.fixture(scope="module")
def models(session, table):
    session.assign_table("D", table=table)
    return datashield_base.ModelsClient(session)


def test_dimensions(stats):
    assert stats.get_dimensions("D")[SERVER] == [ROWS, 5]


def test_column_names(stats):
    assert stats.get_names("D")[SERVER] == ["id", "age", "smoker", "treated", "score"]


def test_mean(stats):
    mean = stats.get_mean("D$age")[SERVER]
    assert mean["EstimatedMean"] == pytest.approx(44.5)
    assert mean["Nvalid"] == ROWS


def test_crosstab(stats):
    rows = {row["_row"]: row for row in stats.get_crosstab("D$smoker", "D$treated")[SERVER]["table"]}
    assert rows["0"] == {"0": 50, "1": 50, "Total": 100, "_row": "0"}
    assert rows["1"] == {"0": 50, "1": 50, "Total": 100, "_row": "1"}
    assert rows["Total"]["Total"] == ROWS


def test_glm(models):
    glm = models.get_glm(formula="D$score ~ D$age", family="gaussian")
    estimates = {coefficient["name"]: coefficient["Estimate"] for coefficient in glm["coefficients"]}
    assert glm["nsubs"] == ROWS
    assert estimates["(Intercept)"] == pytest.approx(10, abs=0.5)
    assert estimates["D$age"] == pytest.approx(2, abs=0.01)
