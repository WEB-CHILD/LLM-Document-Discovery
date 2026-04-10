# Reproducible Demo Pipeline Implementation Plan

**Goal:** README and supporting documentation sufficient for a reviewer or collaborator to reproduce the pipeline.

**Architecture:** README.md provides project overview, prerequisites, quickstart (under 10 commands), CLI reference, and architecture overview. Platform-specific setup guides (Gadi, UCloud) live in separate docs/ files. Quickstart targets the 5-page demo corpus and supports local testing with a smaller model (e.g., Gemma 4) for developers without HPC access.

**Tech Stack:** Markdown

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase implements and tests:

### reproducible-demo.AC4: Documentation
- **reproducible-demo.AC4.1 Success:** README contains quickstart that gets from clone to completed run in under 10 commands

---

<!-- START_TASK_1 -->
### Task 1: Write README.md

**Verifies:** reproducible-demo.AC4.1

**Files:**
- Modify: `README.md` (replace stub with full documentation)

**Implementation:**

Structure the README with these sections:

1. **Title and summary** — One paragraph explaining what the pipeline does (classifies historical web documents using LLMs).

2. **Prerequisites:**
   - Python 3.12+
   - uv package manager
   - HuggingFace account (free, for model access)
   - GPU access (local or HPC) — note that Gemma 4 works for local testing on modest GPUs
   - For HPC: SSH access to Gadi or UCloud

3. **Quickstart (under 10 commands):**
   ```bash
   git clone <repo-url>
   cd LLM-Document-Discovery
   uv sync
   llm-discovery run --platform local --yes       # Fetches demo pages + full pipeline (local GPU)
   datasette corpus.db                            # Browse results
   ```
   Note: `llm-discovery run` includes the fetch step automatically. For HPC:
   ```bash
   llm-discovery run --platform gadi --project <code> --yes
   ```

   Include a "Local testing with smaller model" section:
   ```bash
   VLLM_MODEL=google/gemma-4-12b llm-discovery run --platform local --yes
   ```

4. **CLI Reference:** Table of all subcommands with brief descriptions and key options.

5. **Architecture overview:** Brief description of the pipeline stages (fetch → prep-db → preflight → process → import-results) with the on-node execution model diagram from the design plan.

6. **Platform setup:** Cross-references to:
   - `docs/gadi-setup.md` — NCI Gadi setup (SSH keys, project allocation, module loading)
   - `docs/ucloud-setup.md` — UCloud setup (account, container config)

7. **Development:** How to set up for development (`uv sync --extra dev`, running tests, etc.)

8. **Citation:** Reference to CITATION.cff

**Verification:**
Count commands in quickstart section. Must be ≤10.

**Commit:** `docs: write README with quickstart and CLI reference`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Write platform setup guides

**Files:**
- Create: `docs/gadi-setup.md`
- Create: `docs/ucloud-setup.md`

**Implementation:**

**docs/gadi-setup.md:**
- SSH key setup for `gadi.nci.org.au`
- Project allocation requirements
- Module availability (cuda, python3)
- /scratch space requirements
- HF_TOKEN setup in remote .bashrc
- uv installation on Gadi
- Queue selection: gpuhopper (default, newer GPUs) vs gpuvolta (V100s)

**docs/ucloud-setup.md:**
- UCloud account setup via DeiC
- SSH access to `ucloud@ssh.cloud.sdu.dk` (if applicable)
- Container configuration for Terminal App
- GPU resource selection (H100)
- /work directory structure
- HF_TOKEN setup in container environment

**Verification:**
Read through each guide. Steps should be actionable (specific commands, URLs) not vague ("configure SSH").

**Commit:** `docs: add platform setup guides for Gadi and UCloud`
<!-- END_TASK_2 -->
