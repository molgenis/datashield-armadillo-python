# datashield-armadillo

DataSHIELD Interface implementation for [MOLGENIS Armadillo](https://github.com/molgenis/molgenis-service-armadillo), for use with the [datashield](https://github.com/datashield/datashield-python) Python package.

## Usage

Name the driver in the server entry of your DataSHIELD configuration file:

```yaml
servers:
  - name: armadillo1
    url: https://armadillo.example.org
    token: your-access-token-here
    profile: default
    driver: datashield_armadillo.ArmadilloDriver
```

To log in with your institute account, run the login command. It opens a browser, and saves the access token for the server in `~/.config/datashield/config.yaml`:

```bash
datashield-armadillo-login armadillo1 --url https://armadillo.example.org
```

Run it again when the token has expired; `--url` is only needed the first time.

## Development

```bash
pip install -e ".[dev]"
ruff check src/ tests/
pytest
```

The integration tests are skipped unless `ARMADILLO_URL` is set. To run them, start an Armadillo with a Rock profile that has dsBase installed, then:

```bash
ARMADILLO_URL=http://localhost:8080 ADMIN_PASSWORD=admin PROFILE=default pytest -m integration
```

They create a project with a small generated table, and delete it afterwards.
