# Prompt-authored illustrations

`riso gen` separates creative direction from print treatment:

```text
your original prompt
  subject + viewpoint + organization + spatial action
        ↓
generic medium-only preset
  limited palette + flat adjacency + grain + misregistration
        ↓
finished image + exact prompt/seed/model receipt
```

The user prompt owns what the image depicts. A preset must not contain an
artist name, place, recognizable subject, or borrowed compositional motif.
References shipped with a public-facing preset must be abstract and generated
inside the project or otherwise demonstrably licensed for the purpose.

## Construction choreography proof

The first public-candidate series uses `blueprint-coral`, an original navy,
coral and aqua palette. Its abstract style reference was generated locally by
`riso motif mosaic`; no external artwork was uploaded to ComfyUI.

```bash
riso gen "crews carrying triangular timber roof trusses through an unfinished courtyard housing frame, oblique view from above, staggered diagonal procession between columns, repeated structural bays creating architectural rhythm" --style blueprint-coral --ar 2:3 --seed 301

riso gen "exploded axonometric of a compact modular courtyard house, roof panels, stair flights, wall cassettes and floor decks hovering apart in clearly ordered layers, no people, generous paper space, one compact architectural composition" --style blueprint-coral --ar 2:3 --seed 302

riso gen "top-down construction staging yard with wall panels, stair modules, circular ducts, tools and material bundles arranged in a precise inventory grid on a slab, no people, alternating dense and empty bays" --style blueprint-coral --ar 2:3 --seed 303

riso gen "two mobile cranes lowering a prefabricated stair core into a timber building under construction, low oblique view, suspension cables create crossing diagonals, workers guide the module from opposite corners" --style blueprint-coral --ar 2:3 --seed 304
```

Inspect the exact text that would reach Flux without running the PC:

```bash
riso gen "<your prompt>" --style blueprint-coral --show-prompt
```

Each finished PNG has a JSON sidecar containing `prompt` and `prompt_sent`, so
the creative input and mechanical suffix remain independently auditable.

## Originality gate

Before calling a series public work:

1. Remove the inspiration artist's name and source-specific objects from every
   prompt and preset.
2. Use a palette selected for the new series, not colors sampled from the
   inspiration image.
3. Use an internally generated object-free reference.
4. Change the subject and compositional logic, not just the nouns.
5. Visually inspect every output for accidental source-like motifs.
6. Keep prompts, seeds, settings and source boundaries beside the images.

Passing this gate supports an independent-process claim. It is not legal advice
or a guarantee of exclusive copyright. The shipped Redux adapter is also under
the FLUX.1 dev Non-Commercial License; that restriction travels with these
generated images.
