# Generation box — Phase 0 record

Resolved 2026-08-15 on the **PC** (`desktop-zt`), from inside WSL. No fallback to
the Mac was needed and none was used.

## What the Phase 0 finding actually was

The brief recorded `desktop-zt:8188` as **closed / refused**. That probe ran from
the Mac, across Tailscale and the WSL2 NAT. From inside WSL the diagnosis is
simpler and there is no networking fault at all:

**ComfyUI was not running.** The systemd user unit is installed but deliberately
manual-start (`# Manual start only - no WantedBy directive`), so nothing was
listening for the Mac to reach. Not a NAT problem, not a port-forwarding problem.

## The fix

```bash
systemctl --user start comfyui     # ~10s to answer
```

Unit: `~/.config/systemd/user/comfyui.service`, byte-identical to the copy of
record at `~/code/zohar-infra/pc/services/systemd/comfyui.service`.

```
ExecStart=%h/.venvs/comfyui/bin/python main.py --listen 127.0.0.1 --port 8188 --normalvram
WorkingDirectory=%h/code/comfyui
```

Nothing was installed, edited, or downloaded to get this up.

## Gate evidence — `GET /system_stats`

```json
{
  "system": {
    "os": "linux",
    "comfyui_version": "0.21.1",
    "python_version": "3.12.3",
    "pytorch_version": "2.12.0+cu130",
    "argv": ["main.py", "--listen", "127.0.0.1", "--port", "8188", "--normalvram"]
  },
  "devices": [
    {
      "name": "cuda:0 NVIDIA GeForce RTX 4070 Ti SUPER : cudaMallocAsync",
      "type": "cuda",
      "index": 0,
      "vram_total": 17170956288,
      "vram_free": 9263599616
    }
  ]
}
```

Re-check any time:

```bash
curl -s http://127.0.0.1:8188/system_stats | python3 -m json.tool
```

## Which install is live

`~/code/comfyui` — the one the unit points at, with the venv at `~/.venvs/comfyui`
(torch 2.12.0+cu130, CUDA available). `~/comfy/ComfyUI` is a second checkout whose
`.venv` has no torch; it is not the live install and this repo does not use it.

## Two facts that matter later

**It binds loopback, and that stays.** `--listen 127.0.0.1` means it answers
inside WSL only — not from Windows, not from the Mac over Tailscale. The Mac
probe would still fail with ComfyUI running. **This is the intended setup**
(confirmed by Zohar 2026-08-15): WSL-local is correct, and ComfyUI is not to be
put on Tailscale. Anything driving this pipeline runs inside WSL on the PC. Do
not add `--listen 0.0.0.0` or a Windows portproxy.

**`comfyui-idle-unload.timer` is active** and fires every 2 min, releasing VRAM
after 300s idle. It frees memory, it does not stop the service — the first
generation after a pause pays a reload.

## Model inventory on this box (queried from `/object_info`)

| slot | present |
|---|---|
| checkpoints | `flux1-schnell-fp8.safetensors` (self-contained: CLIP-L + T5 + VAE) |
| unet / diffusion_models | *empty* |
| clip / text_encoders | *empty* |
| style_models | *empty* |
| clip_vision | *empty* |

The brief lists `flux-krea-dev` and `flux_text_encoders` as already pulled. **They
are not on this box** — only schnell-fp8 is. They are presumably on the Mac. Since
schnell-fp8 carries its own encoders, Phase 1 is unblocked and Phase 2 can start on
schnell, but Phase 2 will need two downloads (Redux adapter + its SigLIP vision
encoder) and the Krea-dev question reopens there, not here.
