"""Generates obviously-synthetic placeholder art for the "Sleepy Forest"
seed ThemePack — solid shapes with a label, nothing that could be mistaken
for real illustration. This is a dev tool for exercising the Mad Libs
wizard's plumbing before Tier 2 production art exists; it is not part of
the deployed app and has no runtime dependency on it.

Usage:
    pip install -r requirements-seed.txt
    python generate_seed_placeholders.py
Writes PNGs into ./seed_assets/, matching the cdnKey paths used by
seed_story_content.py.
"""

import os

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join(os.path.dirname(__file__), "seed_assets")


def _font(size):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _labeled(img, text, fill="#FFFFFF"):
    draw = ImageDraw.Draw(img)
    font = _font(max(14, img.width // 12))
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((img.width - w) / 2, (img.height - h) / 2), text, font=font, fill=fill)
    corner_font = _font(10)
    draw.text((6, img.height - 16), "PLACEHOLDER", font=corner_font, fill="#00000066")
    return img


def circle(name, size, color, label, fg="#FFFFFF"):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=color)
    _labeled(img, label, fg)
    img.save(os.path.join(OUT_DIR, name))


def blob(name, size, color, label, fg="#FFFFFF"):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((6, size * 0.2, size - 6, size - 6), radius=size // 3, fill=color)
    draw.ellipse((size * 0.2, 0, size * 0.8, size * 0.45), fill=color)
    _labeled(img, label, fg)
    img.save(os.path.join(OUT_DIR, name))


def background(name, w, h, top, bottom, label):
    img = Image.new("RGB", (w, h), top)
    draw = ImageDraw.Draw(img)
    horizon = int(h * 0.6)
    draw.rectangle((0, horizon, w, h), fill=bottom)
    draw.ellipse((w * 0.72, h * 0.08, w * 0.72 + 160, h * 0.08 + 160), fill="#F5E9C6")
    _labeled(img, label, "#FFFFFFAA")
    img.save(os.path.join(OUT_DIR, name))


def cover(name, w, h, color, label):
    img = Image.new("RGB", (w, h), color)
    _labeled(img, label)
    img.save(os.path.join(OUT_DIR, name))


def face_features(name, size, expression):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size / 2, size / 2
    eye_dx, eye_y = size * 0.16, cy - size * 0.05
    r = size * 0.06
    if expression == "happy":
        draw.ellipse((cx - eye_dx - r, eye_y - r, cx - eye_dx + r, eye_y + r), fill="#241F19")
        draw.ellipse((cx + eye_dx - r, eye_y - r, cx + eye_dx + r, eye_y + r), fill="#241F19")
        draw.arc((cx - size * 0.18, cy, cx + size * 0.18, cy + size * 0.22), 0, 180, fill="#241F19", width=6)
    elif expression == "sleepy":
        draw.arc((cx - eye_dx - r, eye_y, cx - eye_dx + r, eye_y + r * 1.5), 0, 180, fill="#241F19", width=5)
        draw.arc((cx + eye_dx - r, eye_y, cx + eye_dx + r, eye_y + r * 1.5), 0, 180, fill="#241F19", width=5)
        draw.line((cx - size * 0.05, cy + size * 0.12, cx + size * 0.05, cy + size * 0.12), fill="#241F19", width=5)
    elif expression == "curious":
        draw.ellipse((cx - eye_dx - r, eye_y - r, cx - eye_dx + r, eye_y + r), fill="#241F19")
        draw.ellipse((cx + eye_dx - r * 1.3, eye_y - r * 1.3, cx + eye_dx + r * 1.3, eye_y + r * 1.3), outline="#241F19", width=4)
        draw.arc((cx - size * 0.08, cy + size * 0.05, cx + size * 0.12, cy + size * 0.2), 200, 340, fill="#241F19", width=5)
    else:  # surprised
        draw.ellipse((cx - eye_dx - r * 1.4, eye_y - r * 1.4, cx - eye_dx + r * 1.4, eye_y + r * 1.4), fill="#241F19")
        draw.ellipse((cx + eye_dx - r * 1.4, eye_y - r * 1.4, cx + eye_dx + r * 1.4, eye_y + r * 1.4), fill="#241F19")
        draw.ellipse((cx - size * 0.06, cy + size * 0.08, cx + size * 0.06, cy + size * 0.22), fill="#241F19")
    corner_font = _font(9)
    draw.text((4, size - 14), "PLACEHOLDER", font=corner_font, fill="#00000066")
    img.save(os.path.join(OUT_DIR, name))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    background("bg-forest.png", 1024, 768, "#7FB3A8", "#4E8B72", "forest")
    cover("pack-sleepy-forest-cover.png", 512, 384, "#3E7050", "Sleepy Forest")

    blob("barnaby-body.png", 512, "#8A5A34", "BARNABY")
    face_features("expr-happy.png", 512, "happy")
    face_features("expr-sleepy.png", 512, "sleepy")
    face_features("expr-curious.png", 512, "curious")
    face_features("expr-surprised.png", 512, "surprised")

    blob("fox.png", 384, "#D9772E", "FOX")
    blob("rabbit.png", 384, "#C9C2B4", "RABBIT")
    blob("owl.png", 384, "#8E6F4E", "OWL")

    circle("color-golden.png", 320, "#E0A93A", "GOLDEN")
    circle("color-silver.png", 320, "#B9C0C6", "SILVER")
    circle("color-violet.png", 320, "#8E6FA8", "VIOLET")

    print(f"Wrote placeholder PNGs to {OUT_DIR}")


if __name__ == "__main__":
    main()
