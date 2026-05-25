from __future__ import annotations

from pathlib import Path


def draw_square_svg(output_path: str | Path, *, size: int = 64) -> Path:
    if size <= 0:
        raise ValueError("size must be positive")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">\n'
        f'  <rect x="4" y="4" width="{size - 8}" height="{size - 8}" '
        f'stroke="#1f2937" stroke-width="4" fill="#dcfce7" />\n'
        '</svg>\n'
    )
    output.write_text(svg, encoding="utf-8")
    return output


if __name__ == "__main__":
    draw_square_svg(Path("square.svg"))
