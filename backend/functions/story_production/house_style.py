"""Locked, structured house-style definitions.

Two tiers, per the illustration production bible:

GLOBAL_BIBLE holds every constraint that applies to ALL styles alike
(visual complexity, character design, shading restraint, composition,
background complexity, generative restraint, production-asset handling).
HOUSE_STYLES holds only what actually differs between styles: medium,
rendering technique, outline treatment, style-specific shading, and how
reliably the style supports deterministic recoloring later.

Neither is a sentence for an LLM to paraphrase. compile_house_style_block()
renders the identical combined text block every time it's called for a
given style_id -- that text is what actually goes into every
image-generation prompt (master, variant, background, static prop, and the
style's own reference image). Stage 2 gets a short summary of the same
style for context, but never the freedom to rewrite the constraints
themselves.

Plain dicts, not a dataclass: matches this file's own precedent and the
rest of this codebase, which has no dataclass/Pydantic usage to be
consistent with.
"""

# Bump when GLOBAL_BIBLE or any style's constraints change. Folded into
# every generated asset's generationFingerprint, and into the house-style
# reference image's own S3 cache key, so both existing masters/variants/
# backgrounds AND the cached reference they're conditioned on are treated
# as stale after a bible edit -- without needing a separate revision-history
# system.
HOUSE_STYLE_VERSION = 4

GLOBAL_BIBLE = {
    "visual_complexity": [
        "Large simple shapes",
        "Minimal internal detail",
        "Strong, readable silhouettes",
        "Generous negative space",
        "Do not add detail merely to fill empty space",
        "Illustrations must remain readable at small (thumbnail) sizes",
    ],
    "character_design": [
        "Simple geometric construction",
        "Restrained facial features",
        "Minimal anatomy/detail",
        "Expressions use the minimum visual change necessary to read clearly",
        "Simple eyes with small pupils",
        "No oversized glossy eyes, no anime eyes, no Pixar-style eyes, no detailed irises",
        "Simple mouths",
    ],
    "shading_restraint": [
        "Keep shading simple enough that deterministic recoloring stays reliable",
        "No complex gradients, no multicolor reflected light, no realistic "
        "specular highlights, no cinematic lighting",
    ],
    "composition": [
        "One primary action",
        "One clear focal point",
        "Natural character interaction",
        "Avoid excessive symmetry",
        "Preserve negative space",
        "Designed for children's storybook presentation",
    ],
    "background_complexity": [
        "Fewer, larger environmental shapes rather than many small ones",
        "No decorative filler",
        "No dense foliage unless narratively required",
        "Reserve clean open space for characters",
        "Backgrounds support the story rather than compete with it",
    ],
    "production_assets": [
        "Isolated character/prop assets use a plain, empty, non-scenic background",
        "No decorative vignette",
        "No foliage framing",
        "No ornamental background",
        "Behave like a production asset, not a finished poster illustration",
    ],
    "generative_restraint": [
        "text", "typography", "logos", "ornamental frames", "mandalas",
        "random sparkles", "magical particles", "lens flare", "bokeh",
        "glitter", "unnecessary props", "extra characters", "extra animals",
        "flowers", "mushrooms", "wall art", "decorative filler",
    ],
}

HOUSE_STYLES = {
    "cartoon": {
        "medium": "Flat 2D bedtime children's picture-book illustration.",
        "rendering": [
            "Flat color fills only",
            "No painted texture, no watercolor texture, no pencil texture",
            "No visible brush strokes",
            "No 3D rendering, no realistic fur, no individual hairs",
            "Soft, simple lighting that does not materially change character colors",
        ],
        "outlines": [
            "Consistent warm dark contour, uniform width throughout",
            "Rounded stroke ends",
            "No sketchy duplicate lines",
            "No hatching",
        ],
        "shading": [
            "None, or at most one simple flat shadow shape",
        ],
        "recolorability": "HIGH",
    },
    "watercolor": {
        "medium": "Soft children's book watercolor illustration.",
        "rendering": [
            "Translucent overlapping color washes",
            "Soft bleeding edges between color areas",
            "Visible paper-grain texture",
            "No 3D rendering, no photorealistic fur",
        ],
        "outlines": [
            "No hard outlines anywhere",
            "Shape edges defined by color-wash boundaries, not line work",
        ],
        "shading": [
            "Shading only from color pooling slightly darker at the edge of a wash",
        ],
        "recolorability": "LOW",
    },
    "cutout": {
        "medium": "Flat layered-paper cutout children's book illustration.",
        "rendering": [
            "Flat color fills only, no gradients within a single shape",
            "No painted texture, no watercolor texture, no pencil texture",
            "No 3D rendering, no realistic fur",
        ],
        "outlines": [
            "No drawn outline; shapes are defined by silhouette edges",
            "Distinct, crisp silhouette boundaries",
        ],
        "shading": [
            "At most one subtle flat drop-shadow shape between overlapping layers",
        ],
        "recolorability": "HIGH",
    },
    "crayon": {
        "medium": "Warm children's crayon-textured illustration.",
        "rendering": [
            "Textured crayon-fill color areas",
            "Simulated rough crayon strokes within each fill",
            "Warm pastel color palette",
            "No 3D rendering, no realistic fur",
        ],
        "outlines": [
            "Warm dark outline with slight hand-drawn path offset from the fill",
            "Rounded line ends",
            "No hatching",
        ],
        "shading": [
            "None, or at most one simple flat shadow shape",
        ],
        "recolorability": "MEDIUM",
    },
    "sketched": {
        "medium": "Loose pencil-sketch children's book illustration.",
        "rendering": [
            "Visible loose pencil or charcoal linework",
            "Minimal or no fill; at most a very light single-tone wash",
            "Monochrome or one restrained accent color only",
            "No 3D rendering, no realistic fur",
        ],
        "outlines": [
            "Expressive uneven pencil strokes, consistent weight range",
            "Faint visible construction lines are acceptable",
            "No hatching used for shading (line work is the whole rendering)",
        ],
        "shading": [
            "None",
        ],
        "recolorability": "LOW",
    },
    "watermark": {
        "medium": "Low-opacity monotone watermark-style illustration.",
        "rendering": [
            "Low opacity, 20-40%",
            "Monotone or soft dual-tone fill only",
            "Clean flat paths, no stroke",
            "No 3D rendering, no realistic fur",
        ],
        "outlines": [
            "No stroke/outline; shape defined by the flat fill silhouette",
        ],
        "shading": [
            "None beyond the flat low-opacity fill",
        ],
        "recolorability": "MEDIUM",
        # Extends (never replaces) the global composition rules: a
        # watermark sits behind other content instead of standing alone.
        "composition_extra": [
            "Sits subtly behind text",
            "Readable silhouette even at low opacity",
        ],
    },
}


def get_house_style(style_id):
    return HOUSE_STYLES.get(style_id)


def get_recolorability(style_id):
    return HOUSE_STYLES[style_id]["recolorability"]


def compile_house_style_block(style_id):
    """Deterministically render the full locked house-style constraint block
    for style_id -- global bible sections plus this style's own medium/
    rendering/outlines/shading. Identical every time -- never LLM-authored,
    never paraphrased. This is what actually goes into every image prompt.
    """
    style = HOUSE_STYLES[style_id]
    lines = [f"MEDIUM: {style['medium']}"]

    lines.append("RENDERING:")
    lines.extend(f"- {item}" for item in style["rendering"])

    lines.append("OUTLINES:")
    lines.extend(f"- {item}" for item in style["outlines"])

    lines.append("VISUAL COMPLEXITY:")
    lines.extend(f"- {item}" for item in GLOBAL_BIBLE["visual_complexity"])

    lines.append("CHARACTER DESIGN:")
    lines.extend(f"- {item}" for item in GLOBAL_BIBLE["character_design"])

    lines.append("SHADING:")
    lines.extend(f"- {item}" for item in style["shading"])
    lines.extend(f"- {item}" for item in GLOBAL_BIBLE["shading_restraint"])

    lines.append("COMPOSITION:")
    lines.extend(f"- {item}" for item in GLOBAL_BIBLE["composition"])
    lines.extend(f"- {item}" for item in style.get("composition_extra", []))

    lines.append("BACKGROUND COMPLEXITY:")
    lines.extend(f"- {item}" for item in GLOBAL_BIBLE["background_complexity"])

    lines.append("PRODUCTION ASSET HANDLING:")
    lines.extend(f"- {item}" for item in GLOBAL_BIBLE["production_assets"])

    lines.append("PROHIBITED (never include unless explicitly required by the asset):")
    lines.extend(f"- {item}" for item in GLOBAL_BIBLE["generative_restraint"])

    return "\n".join(lines)


def house_style_summary(style_id):
    """Short one-line summary for Stage 2's context only -- not what gets
    sent to the image model. Stage 2 needs to know the style exists and
    roughly what it is, but the actual constraints are injected later,
    verbatim, by compile_house_style_block -- never through Stage 2's own
    retelling.
    """
    return HOUSE_STYLES[style_id]["medium"]
