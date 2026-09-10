"""Deterministic prompt compilation: turns Stage 2's structured visual specs
into final image-model prompts, without ever letting an LLM freely rewrite
locked house-style constraints or a character's immutable identity.

STORY -> Stage 2 (structured spec) -> THIS MODULE (compiled prompt) -> provider

Bumping PROMPT_COMPILER_VERSION signals that recompiling the same structured
input now produces different prompt text -- callers fold it into their
generationFingerprint so existing assets are treated as stale after a
compiler change, without needing a separate history/versioning system.
"""

from house_style import compile_house_style_block, GLOBAL_BIBLE

PROMPT_COMPILER_VERSION = 1

_PRODUCTION_ASSET_HEADER = (
    "PRODUCTION ART ASSET -- not a finished illustration. This is one piece "
    "of a larger children's book illustration system and will be composited "
    "with other assets."
)

_CHARACTER_BIBLE_FIELDS = (
    ("species", "Species"),
    ("approximateAge", "Approximate age"),
    ("headShape", "Head shape"),
    ("earShape", "Ear shape"),
    ("muzzle", "Muzzle/beak/face-front"),
    ("eyeConstruction", "Eye construction"),
    ("bodyProportions", "Body proportions"),
    ("silhouette", "Silhouette"),
    ("clothing", "Clothing"),
    ("accessories", "Accessories"),
    ("outline", "Outline treatment"),
)


def _bible_lines(character_bible):
    lines = []
    for key, label in _CHARACTER_BIBLE_FIELDS:
        value = character_bible.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    palette = character_bible.get("palette")
    if palette:
        lines.append(f"- Color palette: {', '.join(palette)}")
    return lines


def compile_master_prompt(style_id, character_bible, master_prompt):
    """Compile the prompt for a character's first, canonical appearance."""
    house_style = compile_house_style_block(style_id)
    lines = [
        _PRODUCTION_ASSET_HEADER,
        "This image ESTABLISHES the canonical visual identity for a recurring "
        "character. Every later appearance of this character must match it exactly.",
        "",
        "CHARACTER IDENTITY (fixed, to be preserved in every future variant):",
        *_bible_lines(character_bible),
        "",
        f"POSE FOR THIS REFERENCE IMAGE: {master_prompt}",
        "",
        "Isolated single character. Plain, empty, non-scenic background. No props, "
        "no other characters, no scenery.",
        "",
        "HOUSE STYLE (apply exactly):",
        house_style,
    ]
    negative = list(_get_house_style_prohibited(style_id)) + [
        "background scenery", "other characters", "props not part of the character",
    ]
    return "\n".join(lines), negative


def compile_variant_prompt(style_id, character_bible, mutation, is_background_layer=False):
    """Compile the prompt for a variant derived from an existing master.

    Semantics are "edit the existing character," never "draw a new one" --
    the master's own image is passed as the provider's reference separately;
    this text reinforces preservation for providers/fallback paths that also
    consult the prompt itself.
    """
    house_style = compile_house_style_block(style_id)
    mutation_lines = [f"- {key}: {value}" for key, value in mutation.items() if value]
    lines = [
        _PRODUCTION_ASSET_HEADER,
        "This is an EDIT of an existing, already-established character reference "
        "image, not a new character. The reference image supplied alongside this "
        "prompt IS this character's exact, locked visual identity.",
        "",
        "PRESERVE EXACTLY (do not redesign, reinterpret, beautify, or embellish):",
        *_bible_lines(character_bible),
        "- silhouette",
        "- body proportions",
        "- outline treatment and rendering technique",
        "",
        "CHANGE ONLY:",
        *mutation_lines,
        "",
        "DO NOT: redesign the character, reinterpret its proportions, add "
        "accessories, change clothing, change colors, or improve/embellish "
        "the art beyond the requested change.",
        "",
        "HOUSE STYLE (apply exactly):",
        house_style,
    ]
    negative = list(_get_house_style_prohibited(style_id)) + [
        "new character design", "changed proportions", "changed clothing",
        "changed color palette", "added accessories",
    ]
    if not is_background_layer:
        negative.append("background scenery")
    return "\n".join(lines), negative


def compile_background_prompt(style_id, scene):
    """Compile a background prompt from concrete, physical scene fields --
    never from subjective/atmospheric prose.
    """
    house_style = compile_house_style_block(style_id)
    scene_lines = [f"- {key}: {value}" for key, value in scene.items() if value]
    lines = [
        _PRODUCTION_ASSET_HEADER,
        "This is a full-scene background layer.",
        "",
        "SCENE (exact visible geometry, nothing implied beyond this list):",
        *scene_lines,
        "",
        "Do not add visual interest merely to fill empty space. Negative space "
        "is intentional. Do not embellish. Prefer fewer, larger environmental "
        "shape masses over many small ones. No individually drawn leaves, "
        "twigs, or texture marks unless explicitly listed above. No flowers "
        "unless explicitly listed above. No mushrooms unless explicitly listed "
        "above. No tiny decorative objects. No decorative filler. No "
        "characters. No animals. Reserve clean, open space for the characters "
        "this background will be composited with.",
        "",
        "HOUSE STYLE (apply exactly):",
        house_style,
    ]
    negative = list(_get_house_style_prohibited(style_id)) + [
        "characters", "animals", "decorative filler", "flowers", "mushrooms",
        "individually drawn leaves", "tiny decorative objects", "texture marks",
    ]
    return "\n".join(lines), negative


def compile_static_prop_prompt(style_id, physical_prompt):
    """Compile a one-off, non-recurring prop that needs no identity
    continuity (e.g. a single mossy log) -- still physical-description-only,
    still locked to house style, just no character-bible/master machinery.
    """
    house_style = compile_house_style_block(style_id)
    lines = [
        _PRODUCTION_ASSET_HEADER,
        f"SUBJECT (exact physical description, no other elements): {physical_prompt}",
        "",
        "Isolated single object. Plain, empty, non-scenic background. No characters.",
        "",
        "HOUSE STYLE (apply exactly):",
        house_style,
    ]
    negative = list(_get_house_style_prohibited(style_id)) + [
        "characters", "background scenery",
    ]
    return "\n".join(lines), negative


def compile_house_style_reference_prompt(style_id):
    """Compile the prompt for a style's own reference image.

    Generated automatically from the locked global + style bibles and a
    fixed, neutral reference scene -- never authored by a person. This is
    the one reference image every later master/background/static-prop asset
    in this style conditions its Style Guide call on.

    Deliberately does NOT use the "children's book illustration system"
    framing every other prompt in this module uses -- confirmed live, that
    framing reliably primed a full illustrated scene with a human character
    even with explicit isolation/plain-background instructions. This call
    is also always seeded with a blank image at low fidelity (see
    _ensure_house_style_reference in handler.py), never plain
    text-to-image, for the same reason: a genuinely empty seed constrains
    the model to add only what the prompt asks for.
    """
    house_style = compile_house_style_block(style_id)
    lines = [
        "This is a neutral style-reference swatch establishing a house "
        "illustration style. It is not a story scene, not a picture-book "
        "page, and not any specific, named character.",
        "",
        "SUBJECT (fixed, generic, exercises the style's rendering/outline/"
        "shading rules and nothing else): one simple rounded woodland "
        "creature of ambiguous species -- not any real animal, not a "
        "human, not a person, not a child -- standing upright, facing "
        "forward, limbs relaxed at its sides, neutral calm expression, no "
        "clothing, no accessories.",
        "",
        "Isolated single subject on a plain solid-color empty background. "
        "No props, no other figures, no scenery, no buildings, no "
        "landscape, no horizon, no text.",
        "",
        "STYLE (apply exactly):",
        house_style,
    ]
    negative = list(_get_house_style_prohibited(style_id)) + [
        "house", "building", "farmhouse", "cottage", "landscape", "scenery",
        "horizon", "sky", "human", "person", "boy", "girl", "child", "man",
        "woman", "face", "portrait", "clothing", "accessories", "backpack",
        "multiple subjects", "other characters", "named or specific character",
    ]
    return "\n".join(lines), negative


def _get_house_style_prohibited(style_id):
    # Global generative-restraint rules apply to every style alike -- style_id
    # is accepted for a consistent call signature, not because the list varies.
    return GLOBAL_BIBLE["generative_restraint"]
