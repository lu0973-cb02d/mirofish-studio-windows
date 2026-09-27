"""Create the MiroFish desktop icon in PNG and Windows ICO formats."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)

def render(size: int) -> Image.Image:
    scale = 4
    n = size * scale
    image = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = int(n * 0.04)
    radius = int(n * 0.22)
    draw.rounded_rectangle((margin, margin, n-margin, n-margin), radius=radius,
                           fill=(21, 40, 36, 255))
    cx, cy = n * .50, n * .48
    outer = n * .31
    inner = n * .105
    points = []
    for i in range(8):
        angle = -3.14159265/2 + i * 3.14159265/4
        r = outer if i % 2 == 0 else inner
        points.append((cx + r * __import__('math').cos(angle), cy + r * __import__('math').sin(angle)))
    draw.polygon(points, fill=(242, 247, 245, 255))
    # Smaller companion sparkle gives the icon the same visual language as the workbench.
    sx, sy = n * .73, n * .72
    points = []
    for i in range(8):
        angle = -3.14159265/2 + i * 3.14159265/4
        r = n * .115 if i % 2 == 0 else n * .037
        points.append((sx + r * __import__('math').cos(angle), sy + r * __import__('math').sin(angle)))
    draw.polygon(points, fill=(20, 170, 137, 255))
    return image.resize((size, size), Image.Resampling.LANCZOS)

if __name__ == "__main__":
    image = render(1024)
    image.save(OUT / "mirofish-logo.png")
    images = [render(n) for n in (16, 24, 32, 48, 64, 128, 256)]
    images[0].save(OUT / "mirofish-logo.ico", format="ICO", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
