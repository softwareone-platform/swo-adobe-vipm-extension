---
description: 'Python coding conventions and guidelines'
applyTo: '**/*.py'
---

# Python Coding Conventions

## General Instructions
- All configuration **must be provided via environment variables**.
- Do not hardcode configuration values.
- Write maintainable, readable, and predictable code.
- In `pyproject.toml`:
  - Use `*` for **minor versions only**
    ✅ `django==4.2.*`
    ❌ `django==^4.2.2`

- Use consistent naming conventions and follow language-specific best practices.

## Python Instructions
- Use type annotations (PEP 484) - except in the `tests/` folder.
- All public functions, methods, and classes **must include [Google-style docstrings](https://google.github.io/styleguide/pyguide.html)**.
- **Do not add inline comments**; rely on clear code and docstrings instead.
- Function and variable names must be explicit and intention-revealing.
- `pyproject.toml` is the source of truth for code quality rules. Generated code must not violate any configured rules.
- **ruff** is the primary linter for general Python style and best practices.
- **flake8** is used exclusively to run:
  - `wemake-python-styleguide` - Enforces strict Python coding standards ([docs](https://wemake-python-styleguide.readthedocs.io/en/latest/))
  - `flake8-aaa` - Validates the AAA pattern in tests
- Follow PEP 8 unless explicitly overridden by ruff.
- Prefer simple, explicit code over clever or compact implementations.

## Testing
- Use pytest only.
- Tests must be written as **functions**, not classes.
- Test files and functions must use the `test_` prefix.
- Follow ***AAA(Arrange - Act - Assert)*** strictly. See the [flake8-aaa documentation](https://flake8-aaa.readthedocs.io/en/stable/index.html).
- Do **not** use `if` statements or branching logic inside tests.
- Prefer fixtures over mocks whenever possible.
- Avoid duplicating test logic; extract shared setup into fixtures.
- Use `mocker` only when mocking is unavoidable.
- Never use `unittest.mock` directly.
- Always use `spec` or `autospec` when mocking.
- Use `@pytest.mark.parametrize` tests when testing permutations of the same behavior.
