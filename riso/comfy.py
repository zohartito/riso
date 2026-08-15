"""Minimal ComfyUI client: load a workflow, patch it, run it, get PNG bytes.

ComfyUI answers on WSL loopback only, by design — see docs/generation-box.md.
Anything driving this runs inside WSL on the PC.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import requests

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "workflows"
DEFAULT_HOST = "127.0.0.1:8188"

Workflow = Dict[str, Any]

# Where the tunable values live in workflows/flux-redux-styleref.json. Node keys
# are descriptive rather than numeric so this mapping stays readable.
NODE_PROMPT = "positive"
NODE_STYLE_REF = "style_ref"
NODE_STYLE_APPLY = "style_apply"
NODE_LATENT = "latent"
NODE_SAMPLER = "sampler"
NODE_SAVE = "save"


def load_workflow(name: Union[str, Path] = "flux-redux-styleref") -> Workflow:
    """Load an API-format workflow by name or path."""
    path = Path(name)
    if path.suffix.lower() != ".json":
        path = WORKFLOW_DIR / f"{path.name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no workflow at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def apply_params(
    workflow: Workflow,
    *,
    prompt: Optional[str] = None,
    style_ref: Optional[str] = None,
    style_strength: Optional[float] = None,
    seed: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    steps: Optional[int] = None,
    filename_prefix: Optional[str] = None,
) -> Workflow:
    """Return a copy of ``workflow`` with the per-run values patched in.

    Only the values a run varies are exposed. Anything structural — which
    checkpoint, which adapter, the sampler — is a property of the workflow file
    and is edited there, so a run cannot quietly diverge from what is committed.
    """
    patched = json.loads(json.dumps(workflow))  # deep copy, and proves it is JSON

    def node(key: str) -> Dict[str, Any]:
        if key not in patched:
            raise KeyError(f"workflow has no {key!r} node")
        return patched[key]["inputs"]

    if prompt is not None:
        node(NODE_PROMPT)["text"] = prompt
    if style_ref is not None:
        node(NODE_STYLE_REF)["image"] = style_ref
    if style_strength is not None:
        node(NODE_STYLE_APPLY)["strength"] = float(style_strength)
    if seed is not None:
        node(NODE_SAMPLER)["seed"] = int(seed)
    if steps is not None:
        node(NODE_SAMPLER)["steps"] = int(steps)
    if width is not None:
        node(NODE_LATENT)["width"] = int(width)
    if height is not None:
        node(NODE_LATENT)["height"] = int(height)
    if filename_prefix is not None:
        node(NODE_SAVE)["filename_prefix"] = filename_prefix

    return patched


class ComfyError(RuntimeError):
    """ComfyUI refused a prompt or failed while executing it."""


class Comfy:
    """Just enough of the ComfyUI HTTP API to run one workflow at a time."""

    def __init__(self, host: str = DEFAULT_HOST, timeout: float = 30.0) -> None:
        self.base = f"http://{host}"
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())

    # -- health ------------------------------------------------------------

    def system_stats(self) -> Dict[str, Any]:
        response = requests.get(f"{self.base}/system_stats", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def is_up(self) -> bool:
        try:
            self.system_stats()
        except requests.RequestException:
            return False
        return True

    # -- running -----------------------------------------------------------

    def upload_image(self, path: Union[str, Path], overwrite: bool = True) -> str:
        """Push a local image into ComfyUI's input dir; returns its filename.

        Style references live in this repo, not in ComfyUI's input folder, so
        they have to be uploaded before ``LoadImage`` can see them.
        """
        path = Path(path)
        with path.open("rb") as handle:
            response = requests.post(
                f"{self.base}/upload/image",
                files={"image": (path.name, handle, "image/png")},
                data={"overwrite": str(bool(overwrite)).lower()},
                timeout=self.timeout,
            )
        response.raise_for_status()
        uploaded = response.json()
        subfolder = uploaded.get("subfolder") or ""
        name = uploaded["name"]
        return f"{subfolder}/{name}" if subfolder else name

    def submit(self, workflow: Workflow) -> str:
        response = requests.post(
            f"{self.base}/prompt",
            json={"prompt": workflow, "client_id": self.client_id},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise ComfyError(f"prompt rejected: {response.text[:800]}")
        return response.json()["prompt_id"]

    def wait(self, prompt_id: str, timeout: float = 900.0) -> List[bytes]:
        """Block until the prompt finishes; return every image it saved.

        Polled rather than websocket-driven: a run is seconds long and the
        history endpoint is the authority on whether it actually finished.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            response = requests.get(
                f"{self.base}/history/{prompt_id}", timeout=self.timeout
            )
            response.raise_for_status()
            history = response.json()
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyError(f"execution failed: {json.dumps(status)[:800]}")
                return [
                    self._fetch(image)
                    for output in entry.get("outputs", {}).values()
                    for image in output.get("images", [])
                ]
            time.sleep(0.5)
        raise TimeoutError(f"{prompt_id} did not finish within {timeout:.0f}s")

    def _fetch(self, image: Dict[str, str]) -> bytes:
        response = requests.get(
            f"{self.base}/view",
            params={
                "filename": image["filename"],
                "subfolder": image.get("subfolder", ""),
                "type": image.get("type", "output"),
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.content

    def generate(self, workflow: Workflow, timeout: float = 900.0) -> bytes:
        """Run a workflow and return the first image it produced."""
        images = self.wait(self.submit(workflow), timeout=timeout)
        if not images:
            raise ComfyError("workflow finished but saved no image")
        return images[0]
