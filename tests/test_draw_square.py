from test.draw_square import draw_square_svg


def test_draw_square_svg_writes_svg(tmp_path):
    out = tmp_path / "square.svg"

    result = draw_square_svg(out, size=40)

    assert result == out
    svg = out.read_text(encoding="utf-8")
    assert "<rect" in svg
    assert 'width="32"' in svg
