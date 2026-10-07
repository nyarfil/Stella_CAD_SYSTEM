"""Plot measured Z intervals; no mesh rendering or wall-thickness inference."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("report", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
if args.report.resolve() == args.output.resolve():
    parser.error("Report cannot be overwritten")
data = json.loads(args.report.read_text(encoding="utf-8"))
canvas = Image.new("RGB", (1120, 930), "white")
draw = ImageDraw.Draw(canvas)
font_path = Path("C:/Windows/Fonts/segoeui.ttf")
font = ImageFont.truetype(str(font_path), 17) if font_path.exists() else ImageFont.load_default()
title = ImageFont.truetype(str(font_path), 25) if font_path.exists() else font
draw.text((28,16), "ZS-F1 click plate: sampled vertical material intervals", font=title, fill="#15344b")
draw.text((28,55), "Candidate assembly pose | STL units unspecified | bars are samples, not continuous sections", font=font, fill="#35465a")
for panel, x in enumerate((13.0,15.0,17.3)):
    top = 115 + panel*248
    left, width, height = 90, 970, 190
    def p(y,z): return (left+(y+60)/62*width,top+height-(z-10)/28*height)
    draw.text((28,top-27), f"X = {x:g} coordinate units (right click plate)", font=font, fill="#15344b")
    for z in (10,15,20,25,30,35):
        pt = p(-60,z)
        draw.line((pt,p(2,z)),fill="#e4eaf0",width=1)
        draw.text((45,pt[1]-10),str(z),font=font,fill="#35465a")
    for y in (-60,-50,-40,-30,-20,-10,0):
        pt = p(y,10)
        draw.line((pt,p(y,38)),fill="#e4eaf0",width=1)
        draw.text((pt[0]-14,pt[1]+4),str(y),font=font,fill="#35465a")
    for sample in data["samples"]:
        if sample["x"] != x: continue
        for lo,hi in sample["material_intervals"]:
            a,b = p(sample["y"],lo),p(sample["y"],hi)
            draw.line((a,b),fill="#087d96",width=5)
            for point in (a,b): draw.ellipse((point[0]-3,point[1]-3,point[0]+3,point[1]+3),fill="#15344b")
        if not sample["material_intervals"]:
            point=p(sample["y"],11)
            draw.text((point[0]-5,point[1]-9),"x",font=font,fill="#b63c43")
draw.text((28,855), "Horizontal: assembled Y (front at negative Y); vertical: assembled Z. x = no hit at that ray.",font=font,fill="#35465a")
draw.text((28,884), "No inference of normal wall thickness, hinge position, actuation force, return or fatigue.",font=font,fill="#35465a")
args.output.parent.mkdir(parents=True,exist_ok=True)
canvas.save(args.output)
print(args.output)
