"""Génère la marque et l'icône d'un outil AD à partir de l'artwork d'origine.

La marque affichée dans l'interface est le monogramme A surmontant les lettres
« AD ». L'icône d'application, elle, ne garde que le A : à 16 pixels dans la
barre des tâches, les lettres deviennent une tache. Le fond de l'icône porte la
couleur de l'outil — c'est ce qui distingue les applications de la gamme.

    python tools/make_logo.py                          ModbusAI (terracotta)
    python tools/make_logo.py --accent "#3E7CB1" --out assets   un autre outil

Le monogramme est extrait par composantes connexes : les deux plus grandes
forment le A, les deux suivantes de la zone basse forment « AD ». Le cadre en
équerres et le mot « AUTOMATION » sont écartés.
"""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "source" / "logo-ad-512.png"
ACCENT = "#D97757"  # terracotta de la charte (modbusai/ui/palette.py)
ON_ACCENT = "#FFF8F3"
SIZES = (64, 128, 256, 512)


def _components(image: Image.Image) -> list[list[tuple[int, int]]]:
    """Groupes de pixels encrés, du plus grand au plus petit."""
    width, height = image.size
    px = image.load()

    def ink(x: int, y: int) -> bool:
        r, g, b, a = px[x, y]
        return a > 40 and (r + g + b) / 3 < 140

    seen = [[False] * height for _ in range(width)]
    groups: list[list[tuple[int, int]]] = []
    for x0 in range(width):
        for y0 in range(height):
            if not ink(x0, y0) or seen[x0][y0]:
                continue
            queue = deque([(x0, y0)])
            seen[x0][y0] = True
            points: list[tuple[int, int]] = []
            while queue:
                x, y = queue.popleft()
                points.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height and ink(nx, ny) and not seen[nx][ny]:
                        seen[nx][ny] = True
                        queue.append((nx, ny))
            groups.append(points)
    groups.sort(key=len, reverse=True)
    return groups


def _mask(points: list[tuple[int, int]]) -> Image.Image:
    """Silhouette recadrée, en niveaux de gris (255 = plein)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, y0 = min(xs), min(ys)
    mask = Image.new("L", (max(xs) - x0 + 1, max(ys) - y0 + 1), 0)
    px = mask.load()
    for x, y in points:
        px[x - x0, y - y0] = 255
    return mask


def _tinted(mask: Image.Image, size: int, rgb: tuple[int, int, int], margin: float = 0.06) -> Image.Image:
    """Silhouette à la taille voulue, dans la couleur donnée, fond transparent."""
    pad = round(size * margin)
    inner = size - 2 * pad
    scale = min(inner / mask.width, inner / mask.height)
    shape = mask.resize((max(1, round(mask.width * scale)), max(1, round(mask.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    layer = Image.new("RGBA", shape.size, rgb + (0,))
    layer.putalpha(shape)
    canvas.paste(layer, ((size - shape.width) // 2, (size - shape.height) // 2), layer)
    return canvas


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def build(source: Path, out: Path, accent: str, on_accent: str) -> None:
    image = Image.open(source).convert("RGBA")
    groups = _components(image)
    monogram = _mask(groups[0] + groups[1])  # le A
    # « AD » : dans la moitié basse, et plus haut que large — les équerres du
    # cadre, elles, sont des barres larges et plates.
    lettering = []
    for group in groups[2:]:
        xs = [p[0] for p in group]
        ys = [p[1] for p in group]
        width, height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if min(ys) > image.height * 0.6 and height > width:
            lettering.append(group)
    lettering.sort(key=len, reverse=True)
    mark = _mask(groups[0] + groups[1] + lettering[0] + lettering[1])  # le A et « AD »

    out.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        _tinted(mark, size, (0, 0, 0)).save(out / f"mark-{size}.png")
        _tinted(mark, size, (255, 255, 255)).save(out / f"mark-{size}-blanc.png")

    def icon(size: int) -> Image.Image:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=round(size * 0.22), fill=_rgb(accent) + (255,))
        glyph = _tinted(monogram, round(size * 0.74), _rgb(on_accent), margin=0.0)
        canvas.paste(glyph, ((size - glyph.width) // 2, (size - glyph.height) // 2), glyph)
        return canvas

    icon(256).save(out / "modbusai-icon-256.png")
    icon(256).save(
        out / "modbusai.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère la marque et l'icône d'un outil AD.")
    parser.add_argument("--source", type=Path, default=SOURCE, help="logo d'origine (PNG)")
    parser.add_argument("--out", type=Path, default=ROOT / "assets", help="dossier de sortie")
    parser.add_argument("--accent", default=ACCENT, help="couleur de fond de l'icône, ex. #3E7CB1")
    parser.add_argument("--on-accent", default=ON_ACCENT, help="couleur du A sur l'icône")
    args = parser.parse_args()
    build(args.source, args.out, args.accent, args.on_accent)
    print(f"Marque et icône écrites dans {args.out} (accent {args.accent})")


if __name__ == "__main__":
    main()
