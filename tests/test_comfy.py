"""Phase 2: the workflow is structurally sound and patches cleanly.

No live ComfyUI needed — these guard the parts that are wrong on disk rather
than wrong at runtime.
"""

from __future__ import annotations

import json

import pytest

from riso import comfy

# The band measured on 2026-08-15; see refs/srefs.md. Outside it, Redux either
# copies the reference outright or barely tints the output.
USABLE_STRENGTH = (0.05, 0.15)


@pytest.fixture
def workflow():
    return comfy.load_workflow()


def test_every_reference_points_at_a_real_node(workflow):
    """A dangling ["node", slot] link only shows up as a runtime rejection."""
    for name, node in workflow.items():
        for field, value in node["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in workflow, f"{name}.{field} -> missing {value[0]!r}"


def test_the_graph_ends_in_a_save(workflow):
    assert workflow[comfy.NODE_SAVE]["class_type"] == "SaveImage"


def test_the_nodes_apply_params_patches_all_exist(workflow):
    for key in (
        comfy.NODE_PROMPT,
        comfy.NODE_STYLE_REF,
        comfy.NODE_STYLE_APPLY,
        comfy.NODE_LATENT,
        comfy.NODE_SAMPLER,
        comfy.NODE_SAVE,
    ):
        assert key in workflow


def test_redux_is_wired_through_siglip(workflow):
    """Redux reads the reference through CLIP vision; without it there is no style."""
    style_apply = workflow[comfy.NODE_STYLE_APPLY]["inputs"]
    assert style_apply["clip_vision_output"][0] == "style_encode"
    assert workflow["style_encode"]["inputs"]["clip_vision"][0] == "clip_vision"
    assert workflow[comfy.NODE_SAMPLER]["inputs"]["positive"][0] == (
        comfy.NODE_STYLE_APPLY
    ), "the sampler must read the styled conditioning, not the raw prompt"


def test_style_strength_stays_in_the_measured_band(workflow):
    strength = workflow[comfy.NODE_STYLE_APPLY]["inputs"]["strength"]
    low, high = USABLE_STRENGTH
    assert low <= strength <= high, (
        f"strength {strength} is outside the usable band {USABLE_STRENGTH}; "
        "at the node's 1.0 default Redux copies the reference and ignores the prompt"
    )


def test_base_model_is_the_apache_licensed_one(workflow):
    """schnell is Apache-2.0. A silent swap to dev/krea would make output
    non-commercial — see CLAUDE.md."""
    assert workflow["checkpoint"]["inputs"]["ckpt_name"] == (
        "flux1-schnell-fp8.safetensors"
    )


def test_schnell_sampler_settings(workflow):
    sampler = workflow[comfy.NODE_SAMPLER]["inputs"]
    assert sampler["steps"] == 4
    assert sampler["cfg"] == 1.0


def test_apply_params_patches_each_value(workflow):
    patched = comfy.apply_params(
        workflow,
        prompt="a lighthouse",
        style_ref="ref.png",
        style_strength=0.12,
        seed=99,
        width=768,
        height=1024,
        steps=6,
        filename_prefix="proof",
    )
    assert patched[comfy.NODE_PROMPT]["inputs"]["text"] == "a lighthouse"
    assert patched[comfy.NODE_STYLE_REF]["inputs"]["image"] == "ref.png"
    assert patched[comfy.NODE_STYLE_APPLY]["inputs"]["strength"] == 0.12
    assert patched[comfy.NODE_SAMPLER]["inputs"]["seed"] == 99
    assert patched[comfy.NODE_SAMPLER]["inputs"]["steps"] == 6
    assert patched[comfy.NODE_LATENT]["inputs"]["width"] == 768
    assert patched[comfy.NODE_LATENT]["inputs"]["height"] == 1024
    assert patched[comfy.NODE_SAVE]["inputs"]["filename_prefix"] == "proof"


def test_apply_params_leaves_the_original_alone(workflow):
    before = json.dumps(workflow, sort_keys=True)
    comfy.apply_params(workflow, prompt="mutated", seed=1)
    assert json.dumps(workflow, sort_keys=True) == before


def test_apply_params_touches_nothing_it_was_not_given(workflow):
    patched = comfy.apply_params(workflow, prompt="only the prompt")
    assert json.dumps(patched[comfy.NODE_SAMPLER], sort_keys=True) == json.dumps(
        workflow[comfy.NODE_SAMPLER], sort_keys=True
    )


def test_apply_params_reports_a_missing_node():
    with pytest.raises(KeyError):
        comfy.apply_params({"save": {"inputs": {}}}, prompt="x")


def test_missing_workflow_is_a_clear_error():
    with pytest.raises(FileNotFoundError):
        comfy.load_workflow("no-such-workflow")


def test_workflow_loads_by_path_too():
    path = comfy.WORKFLOW_DIR / "flux-redux-styleref.json"
    assert comfy.load_workflow(path) == comfy.load_workflow()
