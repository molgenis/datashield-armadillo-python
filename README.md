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

## Development

```bash
pip install -e ".[dev]"
ruff check src/ tests/
pytest
```
