# Repository Guidelines

## Project Structure & Module Organization
Protos-MCP pairs the Protos structural biology toolkit with Model Context Protocol servers. The packaged library lives in `protos/src/protos`, while reusable datasets and HTML assets sit under `protos/data` and `protos/resources`. MCP entrypoints and adapters are in `mcp_server/core` and `mcp_server/tools`, with ready-to-run drivers such as `claude_server.py` and `ollama_server.py` at the repository root. Tests mirror the code layout: library tests reside in `protos/tests` (configured via `protos/pytest.ini`), and agent-level checks live in `mcp_server/tests`.

## Build, Test, and Development Commands
- `pip install -e protos` – install the Protos package in editable mode for local development.
- `pip install -r requirements-mcp.txt` – bring in MCP-side dependencies for the servers.
- `python claude_server.py` / `python ollama_server.py` – launch the corresponding MCP bridge for manual smoke-testing.
- `python -m pytest protos/tests` – execute the library test suite; add `-m "not integration"` to skip external calls.
- `python -m pytest mcp_server/tests -q` – validate MCP server helpers before touching production tooling.

## Coding Style & Naming Conventions
All Python code follows Black’s 88-character layout with 4-space indentation. Run `black` and `isort` on touched modules before opening a PR; both tools are configured in `protos/pyproject.toml`. Prefer descriptive snake_case for functions, reserve lowerCamelCase only when third-party APIs require it, and keep classes in PascalCase. Add type hints to new public functions and keep `mypy --strict` clean.

## Testing Guidelines
Write focused `test_*.py` modules alongside the feature area they cover and use parametrization instead of bespoke loops. Mark long-running or network-sensitive checks with `@pytest.mark.integration` or `@pytest.mark.slow` so automated runs can filter them. Exercise both the Protos processors and their MCP wrappers, and add a regression test with every bugfix.

## Commit & Pull Request Guidelines
Recent history favors short, present-tense commit titles (for example, `fix error`, `default path`); stay concise but add detail in the body when needed. Reference issue IDs or MCP ticket numbers directly in the description. Pull requests should summarize intent, list primary commands used for validation, and include screenshots or JSON snippets when changing agent-visible responses. Always note follow-up TODOs instead of leaving silent regressions.

## Agent Integration Notes
When extending tool coverage, add capabilities in the relevant `mcp_server/tools/**` modules (including the loader suite in `mcp_server/tools/loader/`) and keep the shared runtime (`mcp_server/runtime.py`) as the single registration point. Regenerate any cached capability reports such as `protos_capability_report.md`, and keep secrets and API tokens out of config defaults—use environment variables picked up by `mcp_server/config.py` during runtime.
