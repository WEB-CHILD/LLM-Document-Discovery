# Tools

## uv
- Invocation: `uv`
- Path: /home/brian/.local/bin/uv
- Notes: run everything via `uv run <tool>`

## ruff
- Invocation: `uv run ruff check`
- Version: 0.15.10
- Notes: config in pyproject.toml; line-length 88. `cli.py` carries pre-existing
  lint debt (F821/F401/E501/PLR0912) unrelated to new modules.

## ty
- Invocation: `uv run ty check <paths>`
- Version: 0.0.24 (pinned in dev deps)
- Notes: `cli.py` has pre-existing invalid-argument-type diagnostics (object vs
  PlatformConfig); new modules are clean.

## pytest
- Invocation: `uv run pytest`
- Version: 9.0.3
- Notes: default deselects `gpu`, `network`, `container` markers.
