# -*- coding: utf-8 -*-
"""Genere nocam.ico — engrenage-B dpan-Bug bleu, fond sombre arrondi."""
import math
from PIL import Image, ImageDraw, ImageFont

S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# fond arrondi sombre
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=96, fill=(11, 15, 20, 255))

cx, cy = S / 2, S / 2
BLUE = (33, 150, 243, 255)

# engrenage : 8 dents
r_out, r_teeth, teeth_w = 176, 214, 0.22
for i in range(8):
    a = i * math.pi / 4
    pts = []
    for da, rr in ((-teeth_w, r_out), (-teeth_w * 0.6, r_teeth),
                   (teeth_w * 0.6, r_teeth), (teeth_w, r_out)):
        pts.append((cx + rr * math.cos(a + da), cy + rr * math.sin(a + da)))
    d.polygon(pts, fill=BLUE)

# anneau de l'engrenage
d.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], fill=BLUE)
d.ellipse([cx - 128, cy - 128, cx + 128, cy + 128], fill=(11, 15, 20, 255))

# "B" central
font = None
for cand in (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
             r"C:\Windows\Fonts\seguisb.ttf"):
    try:
        font = ImageFont.truetype(cand, 200)
        break
    except Exception:
        pass
if font is None:
    font = ImageFont.load_default()

bbox = d.textbbox((0, 0), "B", font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
d.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), "B", font=font, fill=BLUE)

# petite pastille verte "declencheur" en bas a droite (clin d'oeil camera)
d.ellipse([S - 150, S - 150, S - 70, S - 70], fill=(31, 157, 68, 255))
d.ellipse([S - 138, S - 138, S - 82, S - 82], outline=(255, 255, 255, 255), width=8)

img.save("nocam.ico", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
print("nocam.ico OK")
