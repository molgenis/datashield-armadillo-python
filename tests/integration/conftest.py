import os
import uuid

import pytest
import requests
from datashield import DSLoginBuilder, DSSession

DRIVER = "datashield_armadillo.ArmadilloDriver"
SERVER = "armadillo"
ROWS = 200
REQUEST_TIMEOUT_SECONDS = 300


def build_people_csv() -> str:
    rows = ["id,age,smoker,treated,score"]
    for i in range(ROWS):
        age = 20 + i % 50
        noise = 1 if i % 2 else -1
        rows.append(f"{i + 1},{age},{i % 2},{(i // 2) % 2},{10 + 2 * age + noise}")
    return "\n".join(rows) + "\n"


def upload_people_table(admin: requests.Session, url: str, project: str) -> None:
    response = admin.post(
        f"{url}/storage/projects/{project}/csv",
        data={"object": "core/people.csv", "numberOfRowsToDetermineTypeBy": 10},
        files={"file": ("people.csv", build_people_csv(), "text/csv")},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


@pytest.fixture(scope="session")
def settings() -> dict:
    url = os.environ.get("ARMADILLO_URL")
    if not url:
        pytest.skip("ARMADILLO_URL is not set")
    return {
        "url": url.rstrip("/"),
        "password": os.environ.get("ADMIN_PASSWORD", "admin"),
        "profile": os.environ.get("PROFILE", "default"),
    }


@pytest.fixture(scope="session")
def admin(settings: dict):
    http = requests.Session()
    http.auth = ("admin", settings["password"])
    yield http
    http.close()


@pytest.fixture(scope="session")
def profile(settings: dict, admin: requests.Session) -> str:
    name = settings["profile"]
    response = admin.post(f"{settings['url']}/ds-profiles/{name}/start", timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code not in (204, 409):
        pytest.fail(f"Unable to start profile '{name}': HTTP {response.status_code}")
    return name


@pytest.fixture(scope="session")
def table(settings: dict, admin: requests.Session):
    url = settings["url"]
    project = f"pytest{uuid.uuid4().hex[:10]}"
    admin.put(f"{url}/access/projects", json={"name": project}, timeout=REQUEST_TIMEOUT_SECONDS).raise_for_status()
    try:
        upload_people_table(admin, url, project)
        yield f"{project}/core/people"
    finally:
        admin.delete(f"{url}/access/projects/{project}", timeout=REQUEST_TIMEOUT_SECONDS)


@pytest.fixture(scope="session")
def session(settings: dict, profile: str):
    builder = DSLoginBuilder().add(
        SERVER, settings["url"], "admin", settings["password"], profile=profile, driver=DRIVER
    )
    session = DSSession(builder.build())
    session.open()
    yield session
    session.close()


@pytest.fixture(scope="session")
def conn(session: DSSession):
    return session.conns[0]
