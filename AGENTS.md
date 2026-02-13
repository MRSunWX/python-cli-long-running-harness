# Repository Guidelines

## Project Structure & Module Organization
This repository is a Python CLI agent project.
- `main.py`: CLI entrypoint (`init`, `run`, `status`, `chat`, `add-feature`).
- `config.py`: global model, runtime, and command-safety configuration.
- `agent/`: core implementation (`agent.py`, `tools.py`, `security.py`, `progress.py`, `git_helper.py`, `prompts.py`).
- `prompts/`: Markdown prompt templates consumed by `agent/prompts.py`.

Generated runtime files (for example `progress.md` and `feature_list.json`) belong inside target project directories, not this repository root.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate`: create and activate a local virtual environment.
- `pip install -r requirements.txt`: install runtime dependencies.
- `python main.py --help`: view CLI usage and global options.
- `python main.py init ./demo --spec "Create a Flask app"`: initialize a tracked project workspace.
- `python main.py run ./demo --continuous`: run the agent loop until completion.
- `python main.py status ./demo --json`: inspect progress in machine-readable format.
- `python -m py_compile main.py config.py agent/*.py`: quick syntax gate before commit.

## Coding Style & Naming Conventions
- Use Python 3 with 4-space indentation and UTF-8 source files.
- Follow existing naming: `snake_case` for modules/functions/variables, `PascalCase` for classes.
- Keep type hints for public interfaces and dataclass-based models where applicable.
- Keep CLI orchestration in `main.py`; place reusable business logic in `agent/`.
- Maintain prompt file/key consistency with `agent/prompts.py` (`PROMPT_FILES` mapping).

## Testing Guidelines
There is currently no committed automated test suite.
- Add new tests under `tests/` using `pytest` with filenames like `test_security.py`.
- Prioritize tests for command validation (`agent/security.py`) and progress persistence (`agent/progress.py`).
- Before opening a PR, run syntax checks and at least one CLI smoke test (`init` then `status`).

## Commit & Pull Request Guidelines
Git history is currently empty, so no project-specific commit convention exists yet.
- Use Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`) going forward.
- Keep each commit focused on one concern.
- PRs should include: purpose, key changes, verification commands, and sample CLI output for behavior changes.
- Reference related tasks/issues and call out breaking config or prompt updates explicitly.
