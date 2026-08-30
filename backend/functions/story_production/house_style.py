"""Locked, structured house-style definitions.

Each style is a fixed set of constraints, not a sentence for an LLM to
paraphrase. compile_house_style() renders the identical text block every
time it's called for a given style_id -- that text is what actually goes
into every image-generation prompt (master, variant, background). Stage 2
gets a short summary of the same style for context, but never the freedom
to rewrite the constraints themselves.

Plain dicts, not a dataclass: matches this file's own STYLE_RENDERING_RULES
precedent and the rest of this codebase, which has no dataclass/Pydantic
usage to be consistent with.
"""

# Bump when any style's constraints change. Folded into every generated
# asset's generationFingerprint so existing masters/variants/backgrounds are
# treated as stale (regenerated on next request) after a house-style edit,
# without needing a separate revision-history system.
HOUSE_STYLE_VERSION = 1

HOUSE_STYLES = {
    "cartoon": {
        "medium": "Clean digital vector-style children's book illustration.",
        "rendering": [
            "Flat color fills only",
            "No painted texture, no watercolor texture, no pencil texture",
            "No visible brush strokes",
            "No 3D rendering, no realistic fur",
            "No volumetric lighting",
        ],
        "outlines": [
            "Warm dark outline, consistent width throughout",
            "Rounded line ends",
            "No sketchy duplicate lines",
            "No hatching",
        ],
        "shapes": [
            "Large simple shapes",
            "Rounded geometry, no sharp angles",
            "Minimal internal detail",
        ],
        "faces": [
            "Simple eyes with small pupils",
            "Simple mouths",
            "Restrained expressions",
            "No oversized glossy eyes, no anime eyes, no Pixar-style eyes",
            "No detailed irises",
        ],
        "shading": [
            "Minimal shading",
            "At most one simple flat shadow shape where appropriate",
            "No cinematic rim lighting, no dramatic highlights",
        ],
        "composition": [
            "Readable silhouettes",
            "Generous negative space",
            "Low visual clutter",
            "Designed for children's storybook presentation",
        ],
        "prohibited": [
            "text", "typography", "logos", "ornamental frames", "mandalas",
            "random sparkles", "magical particles", "lens flare", "bokeh",
            "glitter", "unnecessary props", "extra characters", "decorative filler",
        ],
    },
    "watercolor": {
        "medium": "Soft children's book watercolor illustration.",
        "rendering": [
            "Translucent overlapping color washes",
            "Soft bleeding edges between color areas",
            "Visible paper-grain texture",
            "No 3D rendering, no photorealistic fur",
            "No volumetric lighting",
        ],
        "outlines": [
            "No hard outlines anywhere",
            "Shape edges defined by color-wash boundaries, not line work",
        ],
        "shapes": [
            "Large simple shapes",
            "Rounded, soft-edged forms",
            "Minimal internal detail",
        ],
        "faces": [
            "Simple eyes with small pupils",
            "Simple mouths",
            "Restrained expressions",
            "No oversized glossy eyes, no anime eyes, no Pixar-style eyes",
            "No detailed irises",
        ],
        "shading": [
            "Shading only from color pooling slightly darker at the edge of a wash",
            "No cinematic rim lighting, no dramatic highlights",
        ],
        "composition": [
            "Readable silhouettes",
            "Generous negative space",
            "Low visual clutter",
            "Designed for children's storybook presentation",
        ],
        "prohibited": [
            "text", "typography", "logos", "ornamental frames", "mandalas",
            "random sparkles", "magical particles", "lens flare", "bokeh",
            "glitter", "unnecessary props", "extra characters", "decorative filler",
        ],
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
        "shapes": [
            "Large simple layered-paper shapes",
            "Rounded geometry",
            "Minimal internal detail",
        ],
        "faces": [
            "Simple eyes with small pupils",
            "Simple mouths",
            "Restrained expressions",
            "No oversized glossy eyes, no anime eyes, no Pixar-style eyes",
        ],
        "shading": [
            "At most one subtle flat drop-shadow shape between overlapping layers",
            "No cinematic rim lighting, no dramatic highlights",
        ],
        "composition": [
            "Readable silhouettes",
            "Generous negative space",
            "Low visual clutter",
            "Designed for children's storybook presentation",
        ],
        "prohibited": [
            "text", "typography", "logos", "ornamental frames", "mandalas",
            "random sparkles", "magical particles", "lens flare", "bokeh",
            "glitter", "unnecessary props", "extra characters", "decorative filler",
        ],
    },
    "crayon": {
        "medium": "Warm children's crayon-textured illustration.",
        "rendering": [
            "Textured crayon-fill color areas",
            "Simulated rough crayon strokes within each fill",
            "Warm pastel color palette",
            "No 3D rendering, no realistic fur, no volumetric lighting",
        ],
        "outlines": [
            "Warm dark outline with slight hand-drawn path offset from the fill",
            "Rounded line ends",
            "No hatching",
        ],
        "shapes": [
            "Large simple shapes",
            "Rounded geometry",
            "Minimal internal detail",
        ],
        "faces": [
            "Simple eyes with small pupils",
            "Simple mouths",
            "Restrained expressions",
            "No oversized glossy eyes, no anime eyes, no Pixar-style eyes",
        ],
        "shading": [
            "Minimal shading",
            "At most one simple flat shadow shape where appropriate",
            "No cinematic rim lighting, no dramatic highlights",
        ],
        "composition": [
            "Readable silhouettes",
            "Generous negative space",
            "Low visual clutter",
            "Designed for children's storybook presentation",
        ],
        "prohibited": [
            "text", "typography", "logos", "ornamental frames", "mandalas",
            "random sparkles", "magical particles", "lens flare", "bokeh",
            "glitter", "unnecessary props", "extra characters", "decorative filler",
        ],
    },
    "sketched": {
        "medium": "Loose pencil-sketch children's book illustration.",
        "rendering": [
            "Visible loose pencil or charcoal linework",
            "Minimal or no fill; at most a very light single-tone wash",
            "Monochrome or one restrained accent color only",
            "No 3D rendering, no realistic fur, no volumetric lighting",
        ],
        "outlines": [
            "Expressive uneven pencil strokes, consistent weight range",
            "Faint visible construction lines are acceptable",
            "No hatching used for shading (line work is the whole rendering)",
        ],
        "shapes": [
            "Large simple shapes",
            "Rounded geometry",
            "Minimal internal detail",
        ],
        "faces": [
            "Simple eyes with small pupils",
            "Simple mouths",
            "Restrained expressions",
            "No oversized glossy eyes, no anime eyes, no Pixar-style eyes",
        ],
        "shading": [
            "Minimal shading",
            "No cinematic rim lighting, no dramatic highlights",
        ],
        "composition": [
            "Readable silhouettes",
            "Generous negative space",
            "Low visual clutter",
            "Designed for children's storybook presentation",
        ],
        "prohibited": [
            "text", "typography", "logos", "ornamental frames", "mandalas",
            "random sparkles", "magical particles", "lens flare", "bokeh",
            "glitter", "unnecessary props", "extra characters", "decorative filler",
        ],
    },
    "watermark": {
        "medium": "Low-opacity monotone watermark-style illustration.",
        "rendering": [
            "Low opacity, 20-40%",
            "Monotone or soft dual-tone fill only",
            "Clean flat paths, no stroke",
            "No 3D rendering, no realistic fur, no volumetric lighting",
        ],
        "outlines": [
            "No stroke/outline; shape defined by the flat fill silhouette",
        ],
        "shapes": [
            "Large simple shapes",
            "Rounded geometry",
            "Minimal internal detail",
        ],
        "faces": [
            "Simple eyes with small pupils",
            "Simple mouths",
            "Restrained expressions",
        ],
        "shading": [
            "No shading beyond the flat low-opacity fill",
        ],
        "composition": [
            "Sits subtly behind text",
            "Readable silhouette even at low opacity",
            "Generous negative space",
        ],
        "prohibited": [
            "text", "typography", "logos", "ornamental frames", "mandalas",
            "random sparkles", "magical particles", "lens flare", "bokeh",
            "glitter", "unnecessary props", "extra characters", "decorative filler",
        ],
    },
}


def get_house_style(style_id):
    return HOUSE_STYLES.get(style_id)


def compile_house_style_block(style_id):
    """Deterministically render the full locked house-style constraint block
    for style_id. Identical every time -- never LLM-authored, never
    paraphrased. This is what actually goes into every image prompt.
    """
    style = HOUSE_STYLES[style_id]
    lines = [f"MEDIUM: {style['medium']}"]
    for section in ("rendering", "outlines", "shapes", "faces", "shading", "composition"):
        lines.append(f"{section.upper()}:")
        lines.extend(f"- {item}" for item in style[section])
    lines.append("PROHIBITED (never include unless explicitly required by the asset):")
    lines.extend(f"- {item}" for item in style["prohibited"])
    return "\n".join(lines)


def house_style_summary(style_id):
    """Short one-line summary for Stage 2's context only -- not what gets
    sent to the image model. Stage 2 needs to know the style exists and
    roughly what it is, but the actual constraints are injected later,
    verbatim, by compile_house_style_block -- never through Stage 2's own
    retelling.
    """
    return HOUSE_STYLES[style_id]["medium"]
