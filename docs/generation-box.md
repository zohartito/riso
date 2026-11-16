# ComfyUI prerequisite and generation box record

## Public bootstrap

`riso` does not install or launch ComfyUI. Run both processes in the same
environment (for WSL, inside the same WSL instance); loopback is the default.
No systemd unit is required or supplied by this repository.

The historical environment below reports ComfyUI **0.21.1**, Python **3.12.3**,
and PyTorch **2.12.0+cu130** on a 16 GB NVIDIA GPU. These are recorded versions,
not established minimum requirements. A clean install and other GPU backends
have not been validated by this repository. Use the upstream
[ComfyUI installation instructions](https://github.com/Comfy-Org/ComfyUI#installing)
for the PyTorch build appropriate to your hardware; do not install the CUDA
build on a Mac.

For a separate Linux/WSL NVIDIA install matching that recorded runtime:

```bash
git clone https://github.com/Comfy-Org/ComfyUI.git
cd ComfyUI
git checkout v0.21.1
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install torch==2.12.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130
python -m pip install -r requirements.txt
```

Download the following files from their publishers, review their model cards
and licences, and place them in this **ComfyUI checkout**, not in `riso`.
Do not substitute a diffusion-only schnell file for the all-in-one checkpoint:
the workflow gets CLIP-L, T5 and VAE from `CheckpointLoaderSimple`.

| Workflow node / loader slot | Exact file and destination | Publisher / provenance entry point |
|---|---|---|
| `checkpoint` / `ckpt_name` | `models/checkpoints/flux1-schnell-fp8.safetensors` | [Comfy-Org FLUX.1 schnell checkpoint](https://huggingface.co/Comfy-Org/flux1-schnell), repackaged from Black Forest Labs schnell |
| `redux` / `style_model_name` | `models/style_models/flux1-redux-dev.safetensors` | [Black Forest Labs FLUX.1 Redux dev](https://huggingface.co/black-forest-labs/FLUX.1-Redux-dev) |
| `clip_vision` / `clip_name` | `models/clip_vision/sigclip_vision_patch14_384.safetensors` | [Comfy-Org SigLIP vision conversion](https://huggingface.co/Comfy-Org/sigclip_vision_384) |

The Phase 0 inventory below predates the Redux downloads. The shipped workflow
needs **all three** files. It uses stock ComfyUI nodes, with no custom-node pack.
Weights are not bundled; access or licence acceptance at a publisher is your
responsibility. The repository has no recorded weight hashes or download
revisions for the historical runs: these links identify download sources, not
proof of byte-identical historical weights. Record the revision and SHA-256 of
your downloads if you need to preserve your environment.

Start ComfyUI in that checkout, with its venv active:

```bash
python main.py --listen 127.0.0.1 --port 8188
```

In a second terminal in the same environment:

```bash
curl --fail http://127.0.0.1:8188/system_stats
curl --fail http://127.0.0.1:8188/object_info > object-info.json
```

Check `/system_stats` for the expected Python, ComfyUI, torch and GPU runtime.
In `object-info.json`, check that every `class_type` in
`riso/workflows/flux-redux-styleref.json` exists, and that each loader's
`input.required` options includes its exact filename from the table. A missing
node indicates an incompatible ComfyUI version; a missing filename indicates
the wrong model folder or a needed restart. A successful health response alone
does not establish that generation works.

Finally, activate **riso's** venv in the riso clone and run the README's `riso
gen` example. Inspect the image for its subject and the JSON sidecar for the
requested model/settings. Connection refusal means ComfyUI is not listening
in this environment; node/model validation errors mean the loader checks above
have not passed. This is a manual generation check, not part of pytest.

## Historical Phase 0 record

Resolved 2026-08-15 on the **PC** (`gpu-pc`), from inside WSL. No fallback to
the Mac was needed and none was used.

## What the Phase 0 finding actually was

The brief recorded `gpu-pc:8188` as **closed / refused**. That probe ran from
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
