# riso — build brief

Spec of record. If context is cleared, re-read this file before doing anything.

---

## Phase 0 findings (already gathered 2026-08-15 — do not re-run these)

Probed from the Mac before the repo was scaffolded:

| check | result |
|---|---|
| `desktop-zt` on Tailscale | **online**, `100.65.251.41`, direct, active |
| `desktop-zt:8188` (ComfyUI) | **closed / refused** — host reachable, nothing listening |
| `desktop-zt:8000` | open (something else; not identified) |
| Mac `127.0.0.1:8188` | no response |
| launchd `com.zohar.comfyui-mac-krea` | loaded, `RunAtLoad=false`, no PID — never started |

**Known breakage — the Mac launchd job is pointed at a dead path.**
The plist runs:

```
/Users/zohartito/code/zohar-infra/mac/flux-krea-dev/run-comfyui-krea.sh   <- does not exist
```

The script actually lives at:

```
/Users/zohartito/projects/_local-only/zohar-infra-files--code/mac/flux-krea-dev/run-comfyui-krea.sh
```

It was swept into `_local-only` during the 2026-07-30 consolidation and the plist
was never updated. `WorkingDirectory` in the plist (`~/comfyui-mac`) is still valid.

Fixing that plist is **not** part of this repo's job — ask Zohar before editing
anything under `~/Library/LaunchAgents` or `_local-only`. For Phase 0 you may run
the script directly to get a ComfyUI instance up.

On the PC side: a refused connection on 8188 means either ComfyUI is not running
in WSL, or it is running but WSL2's NAT is not forwarding the port to the Windows
host (and therefore not to Tailscale). Diagnose which before reaching for a fix.

---

## Goal

Reproduce the editorial/risograph illustration look (Ege Berkina, Gizem Akdag on X)
as a repeatable local pipeline: subject prompt + style reference → flat illustration
→ riso post-pass → export. **Style consistency across a series is the whole point;
one-off pretty images are not the deliverable.**

## What the look is (mechanical spec — verify output against this)

- 3–5 flat colors, zero gradients except grain
- uniform heavy grain across the full frame (screenprint, not photo noise) —
  **2px tooth** at ~1024px (`grain(scale=2)`, the default). Per-pixel grain
  reads as sensor noise, which is the thing this bullet rules out; the earlier
  wording implied per-pixel and contradicted itself. Corrected 2026-08-15.
- no outlines; forms read by color adjacency only
- 1–2px RGB channel misregistration
- optional halftone on a duplicated luminance channel

## Existing assets — do not re-clone or re-download

- ComfyUI on the PC (Tailscale host `desktop-zt`, RTX 4070 Ti SUPER 16 GB):
  WSL at `~/code/comfyui` and `~/comfy/ComfyUI`
- ComfyUI on the Mac: `~/comfyui-mac`
- Weights already pulled: `flux-krea-dev`, `flux1-schnell-fp8`, `flux_text_encoders`
  — **that list describes the Mac, not the PC.** Corrected 2026-08-15 after
  querying `/object_info` on the PC box, which has `flux1-schnell-fp8` and
  nothing else. Do not pull krea-dev onto the PC.
- `~/projects/comfyui-ltx25` is a ComfyUI **fork** for video. Leave it alone.

---

## Phases

Each has a gate. Do not start a phase until the previous gate passes.

### Phase 0 — reachability

Get a ComfyUI instance answering. Prefer the PC (`desktop-zt:8188`); fall back to
the Mac only if the PC cannot be fixed in one pass — and say so explicitly rather
than switching silently. Record what you did in `docs/generation-box.md`.

**Gate:** a JSON response from `/system_stats` with GPU info, and the fix (or the
documented fallback) written down.

### Phase 1 — riso post-processor  ← BUILD THIS FIRST

Python + numpy + Pillow in `riso/post.py`. No Photoshop dependency, no GPU.

- `palette_lock(img, palette)` — nearest-color quantize to a 3–5 color palette
- `grain(img, amount, seed)` — monochromatic, uniform, seeded
- `halftone(img, angle, cell)` — on luminance
- `misregister(img, px)` — per-channel offset
- `compose()` — chains the above from a preset

Palettes are data, in `palettes/*.json`. Two starters are already there
(`tennis-felt`, `riso-nightsea`) — match that schema, do not hardcode colors.

**Gate:** pytest proving (a) same seed → byte-identical output, (b) `palette_lock`
output contains exactly N unique colors. Then run it on any existing image and show
Zohar before/after so he can judge it by eye.

### Phase 2 — ComfyUI style-reference workflow

`workflows/flux-redux-styleref.json` in ComfyUI **API** format (not the UI export).

Flux Redux is the local equivalent of Midjourney `--sref`: it carries style from a
reference image while the text prompt supplies subject and crop. Download only the
Redux adapter — the base Flux weights are already on disk.

**Corrected 2026-08-15:** Redux is two files, not one — the adapter
(`flux1-redux-dev.safetensors`) plus the SigLIP vision encoder it reads the
reference through (`sigclip_vision_patch14_384.safetensors`). Both approved.
The base model stays `flux1-schnell-fp8`: Redux supports schnell, 4 steps keep
iteration fast, and Apache-2.0 removes the non-commercial problem entirely.

**Gate:** two proofs, saved as image pairs in `docs/`:

- (a) same subject prompt + two different style refs → visibly **different** styles
- (b) same style ref + two different subjects → visibly **consistent** style

If (b) fails, the pipeline has no value. Say so rather than shipping it.

### Phase 3 — CLI

```
riso gen "a crowd of tennis spectators seen from behind" --style tennis --ar 3:4
```

Chains Phase 2 → Phase 1 → writes a PNG. Style presets (ref image + palette + post
settings) live in `styles/*.toml`, read with stdlib `tomllib`. Output to `out/`
(gitignored).

**Gate:** one command, from cold, produces a finished image.

---

## Deferred — do not build these now

SDXL + IP-Adapter, style LoRA training, an MCP server, a web UI, Docker, a job queue,
any Photoshop integration. Photoshop is the hand-finishing lane for hero images; the
automated path stays headless. If Phases 1–3 work, these get scoped separately.

## Constraints

- Python, PEP 8, f-strings, `pathlib`. venv is at `.venv`.
- Paths must work on macOS and Windows/WSL — this repo syncs between both via git.
- Prefer stdlib + numpy/Pillow. Justify any other dependency before adding it.
- Short README only. No docs that were not asked for.

## Licensing — put this in the README

Flux dev and Flux Krea-dev are **non-commercial**. Flux schnell is Apache-2.0.
Output from this repo may feed the @zohar_tito account, so flag which model
produced what.

## First step

Before writing code, state the plan: each phase paired with the command that
verifies it. Then start at Phase 0.
