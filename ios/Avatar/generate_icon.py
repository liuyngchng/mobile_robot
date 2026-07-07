#!/usr/bin/env python3
"""
Generate app icon for the Avatar app — a cute robot companion face.
"""

import math
import os
from PIL import Image, ImageDraw

OUT_DIR = os.path.join(
    os.path.dirname(__file__),
    "MobileRobot/Assets.xcassets/AppIcon.appiconset",
)

# ── Palette (matches FaceColors) ────────────────────────────────────────
BG_TOP    = (0x1A, 0x1A, 0x2E)
BG_BOT    = (0x2D, 0x2D, 0x5A)
FACE_FILL = (0xF5, 0xF0, 0xEB)
FACE_RING = (0x45, 0x45, 0x78)
EYE_WHITE = (0xFF, 0xFF, 0xFF)
PUPIL     = (0x17, 0x21, 0x3D)
IRIS      = (0x0F, 0x33, 0x61)
MOUTH     = (0xE8, 0x45, 0x61)
BLUSH_BG  = (0xE8, 0x45, 0x61)   # solid pink (blended via alpha)
EYEBROW   = (0x2E, 0x2E, 0x45)

SIZE = 1024


def gradient_bg(draw, size):
    for y in range(size):
        t = y / size
        r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (size, y)], fill=(r, g, b))


def ellipse_bbox(cx, cy, rw, rh=None):
    rh = rh or rw
    return [cx - rw, cy - rh, cx + rw, cy + rh]


def render_master():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Background gradient
    gradient_bg(draw, SIZE)

    # 2. Face circle
    cx = SIZE / 2
    cy = SIZE * 0.48
    face_r = SIZE * 0.32
    draw.ellipse(ellipse_bbox(cx, cy, face_r), fill=FACE_FILL)
    draw.ellipse(ellipse_bbox(cx, cy, face_r),
                 outline=FACE_RING, width=int(face_r * 0.025))

    # 3. Geometry
    eye_y      = cy - face_r * 0.25
    eye_sp     = face_r * 0.55
    sw         = face_r * 0.45
    sh         = face_r * 0.60
    pr         = face_r * 0.175
    ir         = face_r * 0.225
    mouth_y    = cy + face_r * 0.45
    mouth_hw   = face_r * 0.40
    brow_hl    = face_r * 0.35
    brow_y     = eye_y - face_r * 0.19
    brow_thick = int(brow_hl * 0.35)

    lecx = cx - eye_sp
    recx = cx + eye_sp

    # 4. Blush (drawn as semi-transparent ellipses)
    blush_r  = sw * 0.35
    blush_cy = eye_y + sw * 0.38
    # Draw blush on a separate layer, then alpha-composite
    blush_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    blush_draw = ImageDraw.Draw(blush_layer)
    blush_alpha = 85  # ~33% opacity
    for bcx in (lecx, recx):
        blush_draw.ellipse(
            ellipse_bbox(bcx, blush_cy, blush_r),
            fill=BLUSH_BG + (blush_alpha,),
        )
    img = Image.alpha_composite(img, blush_layer)
    draw = ImageDraw.Draw(img)  # refresh draw after composite

    # 5. Eyebrows (happy)
    for side, ecx in [("left", lecx), ("right", recx)]:
        pts = [
            (ecx - brow_hl, brow_y + brow_hl * 0.15),
            (ecx,            brow_y - brow_hl * 0.45),
            (ecx + brow_hl, brow_y + brow_hl * 0.15),
        ]
        draw.line(pts, fill=EYEBROW, width=brow_thick, joint="curve")

    # 6. Eyes
    pupil_dx = pr * 0.1
    pupil_dy = -pr * 0.1
    for ecx in (lecx, recx):
        # socket
        draw.ellipse(ellipse_bbox(ecx, eye_y, sw/2, sh/2),
                     fill=EYE_WHITE, outline=FACE_RING, width=int(sw * 0.08))
        # iris
        icx = ecx + pupil_dx * 1.5
        icy = eye_y + pupil_dy * 1.5
        draw.ellipse(ellipse_bbox(icx, icy, ir), fill=IRIS)
        # pupil
        draw.ellipse(ellipse_bbox(icx, icy, pr), fill=PUPIL)
        # highlight
        hl_off = pr * 0.35
        hl_r   = pr * 0.28
        draw.ellipse(
            [icx - hl_off - hl_r, icy - hl_off - hl_r,
             icx - hl_off + hl_r, icy - hl_off + hl_r],
            fill=(255, 255, 255, 255),
        )

    # 7. Mouth (happy arc)
    y_off = mouth_hw * 0.9
    draw.arc(
        [cx - mouth_hw * 1.2, mouth_y - y_off,
         cx + mouth_hw * 1.2, mouth_y + y_off],
        start=0, end=180, fill=MOUTH, width=int(mouth_hw * 0.45),
    )

    return img


# ── iOS sizes ────────────────────────────────────────────────────────────

# Each entry: (filename, size)
IOS_SIZES = [
    ("40.png",    40),
    ("60.png",    60),
    ("58.png",    58),
    ("87.png",    87),
    ("80.png",    80),
    ("120.png",  120),
    ("180.png",  180),
    ("1024.png", 1024),
]


def generate_all():
    master = render_master()
    os.makedirs(OUT_DIR, exist_ok=True)

    for fname, size in IOS_SIZES:
        scaled = master.resize((size, size), Image.LANCZOS)
        path = os.path.join(OUT_DIR, fname)
        scaled.save(path, "PNG")
        print(f"  ✓ {fname} ({size}×{size})")

    print(f"\nSaved {len(IOS_SIZES)} icons to {OUT_DIR}")


if __name__ == "__main__":
    generate_all()
