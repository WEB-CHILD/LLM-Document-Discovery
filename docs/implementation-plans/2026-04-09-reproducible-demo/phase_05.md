# Reproducible Demo Pipeline Implementation Plan

**Goal:** `llm-discovery validate` checks remote HPC environment readiness via SSH using fabric.

**Architecture:** platform.py loads platform definitions from config/platforms.yaml using pydantic models. SSH operations use fabric (Connection.run()) for structured remote command execution. Validate subcommand runs a checklist of remote checks with Rich pass/fail output.

**Tech Stack:** fabric, pydantic, pyyaml, Rich, Typer

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase implements and tests:

### reproducible-demo.AC3: HPC deployment
- **reproducible-demo.AC3.3 Success:** `llm-discovery validate` reports pass/fail for each prerequisite (SSH, /scratch, HF_TOKEN, uv)
- **reproducible-demo.AC3.4 Failure:** `llm-discovery deploy` without prior `validate` warns and runs validation first

---

<!-- START_TASK_1 -->
### Task 1: Add fabric dependency to pyproject.toml

**Files:**
- Modify: `pyproject.toml` (add fabric to dependencies)

**Step 1: Add fabric**

Add `"fabric>=3.0"` to the `dependencies` list in pyproject.toml.

**Step 2: Verify**

Run: `uv sync`
Expected: fabric installs successfully alongside existing deps

**Commit:** `chore: add fabric dependency for SSH operations`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Create config/platforms.yaml

**Files:**
- Create: `config/platforms.yaml`

**Implementation:**

Define platform configurations for Gadi and UCloud:

```yaml
# HPC platform definitions
# Used by llm-discovery validate/deploy/retrieve commands

platforms:
  gadi:
    display_name: "NCI Gadi"
    ssh_host: "gadi.nci.org.au"
    remote_base: "/scratch/{project}/llm-discovery"
    gpu_queue: "gpuvolta"
    gpu_type: "V100"
    submission: "pbs"
    modules:
      - "cuda/12.0"
      - "python3/3.12"
    checks:
      - name: "SSH connectivity"
        command: "hostname"
      - name: "/scratch accessible"
        command: "test -d /scratch/{project}"
      - name: "HF_TOKEN set"
        command: "test -n \"$HF_TOKEN\""
      - name: "uv available"
        command: "which uv"

  ucloud:
    display_name: "DeiC UCloud"
    ssh_host: null  # container-based, no SSH
    remote_base: "/work/llm-discovery"
    gpu_type: "H100"
    submission: "api"  # or "manual"
    modules: []  # container has everything
    checks:
      - name: "API endpoint reachable"
        command: null  # checked via HTTP, not SSH
```

The `{project}` placeholder in remote_base is resolved at runtime from environment or CLI option.

**Verification:**
Run: `python -c "import yaml; print(yaml.safe_load(open('config/platforms.yaml'))['platforms'].keys())"`
Expected: `dict_keys(['gadi', 'ucloud'])`

**Commit:** `feat: add platform configuration for Gadi and UCloud`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Create platform.py with pydantic models

**Verifies:** reproducible-demo.AC3.3

**Files:**
- Create: `src/llm_discovery/platform.py`

**Implementation:**

1. **Pydantic models** for platform configuration:
   - `PlatformCheck` — name, command (optional for non-SSH checks)
   - `PlatformConfig` — display_name, ssh_host (optional), remote_base, gpu_type, gpu_queue (optional), submission, modules, checks
   - `PlatformsConfig` — top-level wrapper with `platforms: dict[str, PlatformConfig]`

2. **`load_platforms(config_path: Path) -> PlatformsConfig`** — Load and validate platforms.yaml. Raises clear error if file missing or invalid.

3. **`validate_platform(platform: PlatformConfig, project: str | None = None) -> list[tuple[str, bool, str]]`** — Run each check via fabric SSH connection. Returns list of (check_name, passed, detail). For SSH-based checks:
   ```python
   from fabric import Connection
   conn = Connection(platform.ssh_host)
   result = conn.run(check.command, warn=True, hide=True)
   passed = result.ok
   ```
   For non-SSH platforms (UCloud with ssh_host=None), skip SSH checks.

4. **`resolve_remote_path(platform: PlatformConfig, project: str) -> str`** — Replace `{project}` placeholder in remote_base.

**Testing:**
- reproducible-demo.AC3.3: Test that validate returns pass/fail list for each check
- Test pydantic validation catches missing required fields
- Test that non-SSH platform (UCloud) skips SSH checks gracefully

**Verification:**
Run: `uv run python -c "from llm_discovery.platform import load_platforms; print(load_platforms('config/platforms.yaml'))"`
Expected: Prints parsed platform config without errors

**Commit:** `feat: add platform configuration with pydantic models and fabric SSH`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Wire validate subcommand into CLI

**Verifies:** reproducible-demo.AC3.3, reproducible-demo.AC3.4

**Files:**
- Modify: `src/llm_discovery/cli.py` (replace validate stub)

**Implementation:**

Replace the validate stub with:

```python
@app.command()
def validate(
    platform: str = typer.Option(..., help="HPC platform: gadi or ucloud"),
    project: str = typer.Option(None, help="NCI project code (for Gadi)"),
) -> None:
    """Check remote HPC environment readiness."""
    from llm_discovery.platform import load_platforms, validate_platform
    # Load config, run checks, display Rich table of results
```

The validate command should:
1. Load platforms.yaml
2. Look up the specified platform
3. Run all checks via fabric
4. Display results as a Rich table (green check / red cross per check)
5. Exit with code 0 if all pass, code 1 if any fail

Also add a `_ensure_validated(platform_name: str, project: str | None) -> bool` helper that other commands (deploy) can call. This re-runs validation inline each time — no flag file caching, since the remote environment can change between calls (HPC node reboots, HF_TOKEN expires, etc.). The validation is lightweight (a few SSH commands) so the cost of re-running is negligible.

**Testing:**
- Test that `--help` shows platform and project options
- Test that unknown platform name produces clear error
- Test that AC3.4 is satisfied: deploy calls validation first

**Verification:**
Run: `uv run llm-discovery validate --help`
Expected: Shows --platform and --project options

**Commit:** `feat: wire validate command with Rich status output`
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Tests for platform module

**Verifies:** reproducible-demo.AC3.3

**Files:**
- Create: `tests/test_platform.py`

**Implementation:**

Tests for platform configuration and validation:

1. Test that valid platforms.yaml loads correctly into pydantic models
2. Test that invalid YAML (missing required fields) raises validation error
3. Test that `{project}` placeholder resolution works
4. Test that non-SSH platform (ssh_host=None) skips SSH checks
5. Test validate with mocked fabric Connection (mock Connection.run to simulate pass/fail)

**Testing:**
- Use real YAML parsing (no mock)
- Mock fabric Connection for SSH tests (don't require actual SSH access)
- Test both success and failure scenarios

**Verification:**
Run: `uv run pytest tests/test_platform.py -v`
Expected: All tests pass

**Commit:** `test: add platform configuration tests`
<!-- END_TASK_5 -->
