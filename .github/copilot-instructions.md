# Copilot instructions for CS-PILOT

## Repository overview
- CS-PILOT is a Flask application for HR, accounting, and operational management for associations/collectivities.
- The main entrypoint is `app.py`, which initializes the Flask app and registers feature blueprints from `blueprints/`.
- Project structure and setup are documented in `README.md` and `docs/quick-start.md`; prefer linking to those files instead of duplicating end-user setup steps.

## Code organization
- Implement server features as Flask blueprints under `blueprints/`, following the existing module-per-feature structure.
- When adding a new blueprint or route module, keep imports and blueprint registration in `app.py` consistent with the existing registration pattern.
- Database access uses SQLite via `database.py`; schema changes should go through the migration system in `migration_manager.py` and the SQL files in `migrations/`.
- Templates live in `templates/` and static assets live in `static/`.

## Testing and validation
- Run tests with `python3 -m pytest` from the repository root.
- Reuse fixtures from `tests/conftest.py` before creating new test setup helpers.
- Prefer focused pytest runs for changed areas during iteration, then run the relevant broader validation before finishing.

## Security and configuration
- Do not commit secrets, generated databases, or `.env` contents.
- `SECRET_KEY` and related runtime configuration come from environment variables or the local `.env`; preserve that pattern.
- Follow the existing security-sensitive patterns for authentication, encrypted secrets, CSRF protection, and file handling instead of introducing parallel implementations.

## Change guidelines
- Keep changes small and localized.
- Match the existing French-language user-facing copy and the surrounding code style in the files you edit.
- Before adding new abstractions, check whether an existing helper, fixture, or module already covers the use case.
