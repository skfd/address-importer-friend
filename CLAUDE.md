@FAMILY.md

## This repo

This is the engine. Tests run from here with `.venv` (`python -m pytest`).
`tests/conftest.py` builds a temporary city dir from `config.example.toml`, so
the tests need no city checkout. To try a change against real data, run
`python run.py --city-dir ../<city>-address-import`.
