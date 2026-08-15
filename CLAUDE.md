# riso — project rules

Style-locked flat-illustration pipeline. Subject prompt + style reference →
flat illustration → riso post-pass → export. **Series consistency is the
deliverable; one-off pretty images are not.**

Full spec and phase gates: `docs/BRIEF.md`.

## Environment

- Python 3.11 (pyenv), venv at `.venv`. Activate: `source .venv/bin/activate`
- Deps: numpy, pillow, requests, pytest. Justify anything else before adding it.
- `tomllib` is stdlib in 3.11 — do not add a TOML dependency.
- `argparse` is stdlib — do not add click/typer.
- Use `pathlib`, not `os.path`. Paths must work on macOS **and** Windows/WSL —
  this repo syncs between both machines via git.

## Generation box

- Primary: PC `desktop-zt` over Tailscale, RTX 4070 Ti SUPER **16 GB**.
  ComfyUI in WSL at `~/code/comfyui` and `~/comfy/ComfyUI`.
- Fallback: Mac `~/comfyui-mac`.
- Weights already pulled — **do not re-download**: `flux-krea-dev`,
  `flux1-schnell-fp8`, `flux_text_encoders`.
- `~/projects/comfyui-ltx25` is a ComfyUI **fork** pinned for LTX video.
  Do not touch it, do not import from it.

## Licensing

Flux dev and Flux Krea-dev are **non-commercial**. Flux schnell is Apache-2.0.
Output may feed the @zohar_tito account — record which model produced each image.

## Out of scope

SDXL + IP-Adapter, style LoRA training, MCP server, web UI, Docker, job queue,
Photoshop integration. Photoshop is the hand-finishing lane for hero images;
the automated path stays headless. Scope these separately after Phase 3 lands.

## Working agreement

Each phase has a gate. Do not start a phase until the previous gate passes.
If a gate fails, say so plainly — do not ship past it.
