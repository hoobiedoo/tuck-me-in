"""Deterministic generation for visual primitives that don't need (and are
actively harmed by) a generative image model. A "golden glow" sent through
an image model comes back as a decorative medallion or magical ornament --
a radial gradient is just math.
"""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

# Semantic color names Stage 2 may emit for a glow's "color" field. If Stage 2
# instead supplies a literal hex value it's used as-is -- this is only a
# convenience lookup for the common natural-language names.
GLOW_COLOR_HEX = {
    "golden": "#FFD873",
    "gold": "#FFD873",
    "silver": "#D8E4EC",
    "silvery": "#D8E4EC",
    "green": "#B7F0B0",
    "pale green": "#B7F0B0",
    "rose": "#FFC4D6",
    "pink": "#FFC4D6",
    "blue": "#BFE0FF",
    "warm white": "#FFFDF2",
    "white": "#FFFDF2",
}


def resolve_glow_color(color):
    if not color:
        raise ValueError("color is required for a radial_glow effect")
    if color.startswith("#"):
        return color
    normalized = color.strip().lower()
    resolved = GLOW_COLOR_HEX.get(normalized)
    if resolved:
        return resolved
    # Bedrock reliably reaches for a recognized color word but wraps it in a
    # descriptive modifier it wasn't asked for ("pale silver", confirmed
    # live) -- match any known color name appearing in the phrase, longest
    # (most specific) key first, rather than requiring an exact match.
    for key in sorted(GLOW_COLOR_HEX, key=len, reverse=True):
        if key in normalized:
            return GLOW_COLOR_HEX[key]
    raise ValueError(
        f"Unknown glow color '{color}'; use a hex value or one of: "
        f"{', '.join(sorted(GLOW_COLOR_HEX))}."
    )


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def generate_radial_glow(color, size=512, falloff=2.0, opacity=0.85):
    """Return PNG bytes: a soft radial glow, transparent background, centered.

    falloff > 1 concentrates brightness toward the center (sharper falloff);
    falloff == 1 is linear; falloff < 1 spreads brightness further out.
    opacity is the peak alpha at the very center, 0-1.
    """
    rgb = _hex_to_rgb(resolve_glow_color(color))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    center = size / 2
    max_radius = size / 2
    pixels = img.load()
    for y in range(size):
        for x in range(size):
            distance = ((x - center) ** 2 + (y - center) ** 2) ** 0.5
            fraction = min(distance / max_radius, 1.0)
            alpha = max(0.0, (1.0 - fraction) ** falloff) * opacity
            pixels[x, y] = (*rgb, int(alpha * 255))
    img = img.filter(ImageFilter.GaussianBlur(radius=size * 0.02))
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
