from __future__ import annotations

import os
from pathlib import Path


def draw_circle_svg(output_path: str | Path, *, radius: int = 48) -> Path:
    if radius <= 0:
        raise ValueError("radius must be positive")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    size = radius * 2 + 8
    center = size // 2
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">\n'
        f'  <circle cx="{center}" cy="{center}" r="{radius}" '
        f'stroke="#1f2937" stroke-width="4" fill="#dbeafe" />\n'
        "</svg>\n"
    )
    output.write_text(svg, encoding="utf-8")
    return output


def main(output_path: str | Path | None = None) -> Path:
    env_output = os.environ.get("PHYSICAL_AGENT_OUTPUT_PATH") or os.environ.get("OUTPUT_PATH")
    target = Path(output_path or env_output or "circle.svg")
    return draw_circle_svg(target)


if __name__ == "__main__":
    main()
