---
name: python-sqlite-project
description: Apply this project's Python, SQLite, GitHub, testing, and maintainable architecture standards when creating, editing, reviewing, or testing project code. Also use when explicitly requested by name.
---

# Project Engineering Standards

## Role

Act as a senior Python software engineer specializing in SQLite, GitHub workflows, testing, and maintainable project architecture.

## Python Standards

- Use Python 3.12+ unless the project specifies otherwise.
- Follow PEP 8 and use type hints.
- Prefer small, reusable functions and modular code.
- Avoid unnecessary dependencies.
- Use `pathlib` for filesystem operations.
- Use `logging` instead of print statements for application diagnostics.
- Use `pyproject.toml` for project configuration.

## SQLite Database

- Use SQLite for persistent local storage.
- Always use parameterized SQL queries.
- Never construct SQL queries by directly interpolating user input.
- Use foreign keys and appropriate indexes.
- Enable `PRAGMA foreign_keys = ON` for every connection.
- Use transactions for operations that must succeed or fail together.
- Store schema migrations in `database/migrations/`.
- Never delete or overwrite an existing database without explicit permission.
- Keep database access separate from business logic.
- Use context managers and close connections properly.

## Git & GitHub

- Use descriptive, focused commits.
- Follow the repository's existing branching conventions.
- Never force-push or rewrite shared history without permission.
- Do not commit secrets, credentials, virtual environments, or local SQLite database files.
- Run relevant tests before proposing a commit.
- Use GitHub Actions for automated tests when appropriate.
- Provide concise pull request descriptions summarizing changes and testing.

## File Structure

- Keep source code inside `src/`.
- Keep tests inside `tests/`.
- Keep database code inside `database/`.
- Keep reusable utilities inside `utils/`.
- Keep scripts inside `scripts/`.
- Avoid large files containing unrelated functionality.
- Use descriptive filenames and consistent naming conventions.
- Follow existing project conventions before introducing new directories.
- Avoid circular imports.

## Testing

- Use pytest.
- Write tests for new functionality and bug fixes.
- Use temporary SQLite databases for database tests.
- Test edge cases and error handling.
- Do not modify production data during tests.
- Run tests after making changes.

## Working Process

1. Inspect the existing repository and understand its architecture.
2. Identify relevant files before making modifications.
3. Explain the proposed changes briefly.
4. Implement the smallest maintainable solution.
5. Add or update tests.
6. Run relevant tests and report results.
7. Summarize modified files and any remaining issues.

## Important Rules

- Never delete files without understanding their purpose.
- Never introduce breaking schema changes without warning.
- Never hardcode secrets or credentials.
- Never silently change public interfaces.
- Prefer simplicity over unnecessary abstraction.
- Ask before destructive operations.
- Preserve existing functionality unless explicitly instructed otherwise.
