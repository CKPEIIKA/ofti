from __future__ import annotations

from ofti.core.blockmesh import parse_vertices_node, parse_vertices_text


def test_parse_vertices_text() -> None:
    text = """
    vertices
    (
        (0 0 0)
        (1 0 0)
        (1 1 0)
        (0 1 0)
    );
    """
    vertices = parse_vertices_text(text)
    assert len(vertices) == 4
    assert vertices[0] == (0.0, 0.0, 0.0)
    assert vertices[-1] == (0.0, 1.0, 0.0)


def test_parse_vertices_node() -> None:
    node = [
        [0, 0, 0],
        (1.5, 0, 0),
        ["bad", 1, 2],
        [0, 1, 0],
    ]
    vertices = parse_vertices_node(node)
    assert vertices == [(0.0, 0.0, 0.0), (1.5, 0.0, 0.0), (0.0, 1.0, 0.0)]
