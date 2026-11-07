# Working on the RSI cross swing bot

## Setup

```
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 setup
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 ci
```

Copy `.env.example` to `.env`. Never commit secrets or `data/`.

## Definition of done

1. `scripts\dev.ps1 ci` is green: ruff, mypy strict, import-linter, tests, coverage ≥ 90.
2. New behaviour has tests, including the failure case.
3. Strategy changes bump the version in `pyproject.toml` and `src/rsi_cross_swing_bot/__init__.py`.
4. No secrets or runtime `data/` in the diff.

## Architecture

- Strategy (`core`, `indicators`, `engine`, `risk`) does no I/O.
- Only `adapters.ib` imports `ib_async`.
- Layers only import downwards (`import-linter` in CI).

## Dependencies

Pin with `scripts\dev.ps1 lock`, then `ci`, then commit `requirements.lock` and `requirements-dev.lock` together.
