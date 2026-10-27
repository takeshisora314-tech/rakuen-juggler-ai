"""Render a simple code-native reel icon; no remote assets or fonts required."""
from pathlib import Path
from PIL import Image, ImageDraw


def build(path=Path(__file__).with_name('app-icon.png')):
    image=Image.new('RGB',(512,512),'#111827')
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((92,158,420,354),radius=32,fill='#fbbf24')
    for x in (110,211,312):
        draw.rounded_rectangle((x,181,x+89,331),radius=12,fill='#fff7ed')
        draw.polygon([(x+15,210),(x+75,210),(x+75,229),(x+44,303),
                      (x+20,303),(x+51,232),(x+15,232)],fill='#dc2626')
    image.save(path)


if __name__=='__main__': build()
