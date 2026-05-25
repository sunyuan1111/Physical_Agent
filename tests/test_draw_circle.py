from scripts.draw_circle import draw_circle_svg


def test_draw_circle_svg_writes_svg(tmp_path):
    out = tmp_path / "circle.svg"

    result = draw_circle_svg(out, radius=32)

    assert result == out
    svg = out.read_text(encoding="utf-8")
    assert "<circle" in svg
    assert 'r="32"' in svg
