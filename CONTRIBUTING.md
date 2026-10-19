# Contributing

Thanks for contributing.

## Development workflow

1) Create a feature branch.
2) Make focused changes.
3) Run tests locally.
4) Update documentation when behavior or interfaces change.
5) Open a PR with context, impact, and test evidence.

## Local dev

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest tests/
```

## Coding conventions

- Keep BAPI responses in standard shape:
  `{"RETURN": [...], "DATA": ...}`.
- Use parameterized SQL only (never string interpolation for SQL values).
- Keep one transaction boundary per BAPI call (`with get_conn() as conn:`).
- Prefer simple plain functions over framework-heavy abstractions.

## Adding a new BAPI tool

1) Add a `BAPI_*` function in the relevant `server/bapi/*.py` module.
2) Return `bapi_result(...)` or `bapi_error(...)`.
3) Add tests in `tests/test_bapi.py`.
4) Update docs (`README.md` and/or `docs/*`) to include the new tool.

No manual registration is needed: `server/mcp_server.py` auto-discovers
`BAPI_*` functions.

## Security-sensitive changes

If your change touches auth, roles, sessions, or admin endpoints:

- add or update tests in `tests/test_security.py`
- describe migration or compatibility impact in PR description

## Database and migration changes

- Base schema lives in `data/schema.sql`.
- Add forward-only migrations as `data/migration_XXX.sql`.
- Keep migrations idempotent where feasible.
- Verify both fresh-init and migration paths with tests.

## Pull request checklist

- [ ] `pytest tests/` passes
- [ ] docs updated for any user-visible or API-visible changes
- [ ] migrations included (if schema changed)
- [ ] no secrets or generated DB files added unintentionally
