"""
Command that logs in to an Armadillo server and saves the access token in the DataSHIELD configuration file.
"""

import argparse
import os
from pathlib import Path

import requests
import yaml
from molgenis_auth import MolgenisAuthClient

CONFIG_FILE = Path("~/.config/datashield/config.yaml")
DRIVER = "datashield_armadillo.ArmadilloDriver"
SCOPES = "openid offline_access"
REQUEST_TIMEOUT_SECONDS = 30


def read_config(path: Path) -> dict:
    if not path.exists():
        return {"servers": []}
    with open(path) as f:
        config = yaml.safe_load(f) or {}
    config.setdefault("servers", [])
    return config


def write_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    path.chmod(0o600)


def find_server(config: dict, name: str) -> dict | None:
    return next((server for server in config["servers"] if server.get("name") == name), None)


def add_server(config: dict, name: str, url: str) -> dict:
    server = {"name": name, "url": url}
    config["servers"].append(server)
    return server


def read_auth_settings(url: str) -> dict:
    response = requests.get(f"{url.rstrip('/')}/actuator/info", timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()["auth"]


def request_access_token(url: str) -> str:
    auth = read_auth_settings(url)
    client = MolgenisAuthClient(auth_server=auth["issuerUri"], client_id=auth["clientId"], scopes=SCOPES)
    return client.device_flow_auth()["access_token"]


def parse_arguments(argv: list | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="datashield-armadillo-login",
        description="Log in to an Armadillo server and save the access token in the DataSHIELD configuration file.",
    )
    parser.add_argument("server", help="name of the server in the DataSHIELD configuration file")
    parser.add_argument("--url", help="address of the Armadillo server; required when the server is not listed yet")
    parser.add_argument("--config", type=Path, default=CONFIG_FILE, help=f"configuration file (default: {CONFIG_FILE})")
    return parser.parse_args(argv)


def main(argv: list | None = None) -> None:
    args = parse_arguments(argv)
    path = args.config.expanduser()
    config = read_config(path)
    server = find_server(config, args.server)
    if server is None and args.url is None:
        raise SystemExit(f"No server named '{args.server}' in {path}: give its address with --url")
    if server is None:
        server = add_server(config, args.server, args.url)
    elif args.url is not None:
        server["url"] = args.url
    server.setdefault("driver", DRIVER)
    server["token"] = request_access_token(server["url"])
    write_config(path, config)
    print(f"Token for '{args.server}' saved in {path}")
