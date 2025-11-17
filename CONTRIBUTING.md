# Contributing to AgentsFlow

## Development Setup

This project uses `uv` for dependency management and includes automated code quality gates.

### Installing Dependencies

```bash
# Install all dependencies including dev tools
uv sync --all-extras
```

## Code Quality Gates

All PRs must pass the following automated gates:

### 1. Dependency Lock File Verification

The `uv.lock` file must be up to date with `pyproject.toml`:

```bash
uv lock --frozen
```

**Important**: Always run this after modifying dependencies in `pyproject.toml`. If you add or update dependencies, run `uv lock` (without `--frozen`) to update the lock file, then commit both files.

### 2. Code Formatting (Ruff)

Code must be formatted using ruff's opinionated formatter (100 character line length):

```bash
# Check formatting
uv run ruff format --check .

# Auto-fix formatting
uv run ruff format .
```

### 3. Linting (Ruff)

Code must pass linting checks including:
- pycodestyle (E, W)
- pyflakes (F)
- isort (I)
- pep8-naming (N)
- pyupgrade (UP)
- flake8-bugbear (B)
- flake8-comprehensions (C4)
- flake8-simplify (SIM)

```bash
# Check linting
uv run ruff check .

# Auto-fix linting issues
uv run ruff check --fix .
```

### 4. Type Checking (mypy)

Code must pass strict type checking with mypy:

```bash
uv run mypy agentsflow tests
```

### 5. Type Checking (pyright)

Code must also pass type checking with pyright (complementary to mypy):

```bash
uv run pyright agentsflow tests
```

## Pre-commit Hooks

To automatically run all quality gates before each commit:

```bash
# Install pre-commit hooks
uv run pre-commit install

# Run manually on all files
uv run pre-commit run --all-files
```

The pre-commit hooks will:
- Format code with ruff
- Fix linting issues automatically
- Run type checks with both mypy and pyright
- Verify dependency lock file when pyproject.toml changes

## Running All Gates Locally

Before submitting a PR, ensure all gates pass:

```bash
# Format code
uv run ruff format .

# Fix linting
uv run ruff check --fix .

# Type check
uv run mypy agentsflow tests
uv run pyright agentsflow tests

# Verify lock file
uv lock --frozen
```

## CI/CD

All PRs automatically run these gates via GitHub Actions. The workflow is defined in `.github/workflows/lint-and-type-check.yml`.
