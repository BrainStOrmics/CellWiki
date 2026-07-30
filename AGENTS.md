# Repository Guidelines

## Project Structure & Module Organization

Backend code lives in `src/cellwiki/`. Keep domain models and invariants in
`domain/`, orchestration and persistence in `services/`, HTTP endpoints in
`api/`, and database changes in `migrations/`. The React/Vite interface is in
`frontend/src/`; its Tauri shell is in `frontend/src-tauri/`, and browser tests
are in `frontend/e2e/`. Python tests live in `tests/`, with reusable inputs in
`tests/fixtures/`. Treat `data/`, `wiki/`, `cache/`, and `output/` according to
the ownership and publication rules documented in `CONTEXT.md`.

## Build, Test, and Development Commands

Use PowerShell from the repository root:

```powershell
uv sync --extra dev --extra desktop   # Create/update the Python environment
.venv\Scripts\cellwiki.exe dev        # Run the coordinated local stack
.venv\Scripts\python.exe -m pytest -q # Run backend tests
Set-Location frontend
npm ci                                # Install pinned frontend dependencies
npm test                              # Run Vitest once
npm run build                         # Type-check and build the web UI
npm run test:e2e                      # Run Playwright desktop-flow tests
npm run desktop:dev                   # Launch the Tauri development app
```

Copy `.env.example` to `.env` for local configuration. Never commit `.env`.

## Coding Style & Naming Conventions

Python uses four-space indentation, type hints, and `snake_case`; classes use
`PascalCase`. Run `uv run ruff check src tests` and `uv run mypy src` for
linting and type checks. TypeScript uses two spaces, double quotes,
`PascalCase` React components, and `camelCase` functions. Match nearby code.
Comments and docstrings should explain intent, architectural boundaries, or
safety constraints—not restate obvious statements.

## Testing Guidelines

Name Python tests `test_*.py` and frontend tests `*.test.ts` or `*.test.tsx`.
Add a focused regression test for each bug and contract tests for API or domain
changes. Run the smallest relevant test first, then the full affected suite.
Real-provider checks require explicit credentials and are not substitutes for
repeatable local tests.

## Commit & Pull Request Guidelines

Recent history favors concise, imperative subjects, often scoped like
`docs: make public documentation self-contained` or
`refactor: rebuild CellWiki architecture`. Keep commits logically focused.
Pull requests should explain what changed and why, link related issues, list
exact verification commands, and call out migrations, security/data impact,
and documentation changes. Include screenshots for visible UI changes. Do not
describe local results as hosted CI results.

## Architecture & Security

Read `CONTEXT.md`, `CONTRIBUTING.md`, and `SECURITY.md` before changing domain
behavior. Formal knowledge writes must follow
`ChangeSet -> Approval -> CentralWriter -> Verification`. Do not commit
credentials, runtime databases, generated builds, or private project data.
