"""Create the MiroFish desktop icon without network access or external assets.

The SVG is the source of truth for the mark. Pillow is used for the Windows
PNG/ICO variants so the desktop shell and tray do not depend on an image
service or a separate graphics toolchain.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def draw_mark(size: int) -> Image.Image:
    scale = size / 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def xy(values):
        return tuple(round(value * scale) for value in values)

    draw.rounded_rectangle(xy((8, 8, 248, 248)), radius=round(58 * scale), fill="#122e28")
    # The same eight-point star used by the Studio brand and the installer.
    def star(center, outer, inner, fill):
        points = []
        for index in range(16):
            angle = -3.141592653589793 / 2 + index * 3.141592653589793 / 8
            radius = outer if index % 2 == 0 else inner
            points.append((center[0] + radius * __import__("math").cos(angle),
                           center[1] + radius * __import__("math").sin(angle)))
        draw.polygon([xy(point) for point in points], fill=fill)

    star((128, 128), 94, 31, "#f2f7f5")
    star((197, 190), 32, 10, "#14aa89")
    return image


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 64, 128, 256, 512, 1024):
        draw_mark(size).save(ASSETS / f"mirofish-{size}.png", optimize=True)
    # Electron accepts a multi-resolution ICO on Windows. Pillow keeps all
    # sizes in one file, avoiding the blurry default application icon.
    draw_mark(256).save(
        ASSETS / "mirofish.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    # Tray icons should be small and transparent around the mark.
    draw_mark(32).save(ASSETS / "mirofish-tray.png", optimize=True)
    print(f"generated icons in {ASSETS}")


if __name__ == "__main__":
    main()
