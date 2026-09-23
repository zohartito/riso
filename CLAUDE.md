# riso — project rules

Style-locked flat-illustration pipeline with three lanes: `riso gen` for
ComfyUI subjects, `riso motif` for deterministic geometric posters, and
`riso stylize` for existing images. All three end in the same riso post-pass.
**Series consistency is the deliverable; one-off pretty images are not.**

Full spec and phase gates: `docs/BRIEF.md`.

## Environment

- Python **3.13.13** in the PC/WSL venv at `.venv` (an earlier note here said
  3.11 — wrong). Activate: `source .venv/bin/activate`. Keep syntax 3.11-safe:
  the Mac venv has not been checked from this box.
- Deps: numpy, pillow, requests, pytest. Justify anything else before adding it.
- `tomllib` is stdlib from 3.11 on — do not add a TOML dependency.
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

**`flux1-schnell-fp8` (Apache-2.0) is the pipeline default** — decided
2026-08-15. It removes the non-commercial problem entirely, and 4 steps keep
iteration fast. Flux dev and Flux Krea-dev are **non-commercial**; krea-dev is
not on the PC box and is not to be pulled there.

Output may feed the @zohar_tito account — record which model produced each image.

## Out of scope

SDXL + IP-Adapter, style LoRA training, MCP server, web UI, Docker, job queue,
Photoshop integration. Photoshop is the hand-finishing lane for hero images;
the automated path stays headless. Scope these separately after Phase 3 lands.

## Working agreement

Each phase has a gate. Do not start a phase until the previous gate passes.
If a gate fails, say so plainly — do not ship past it.
