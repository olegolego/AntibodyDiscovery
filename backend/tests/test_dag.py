import pytest
from app.core.dag import topological_sort, upstream_outputs
from app.models.pipeline import Pipeline, PipelineEdge, PipelineNode


def _pipeline(*edges: tuple[str, str]) -> Pipeline:
    node_ids = {n for e in edges for n in e}
    nodes = [PipelineNode(id=n, tool="echo", params={}, position={"x": 0, "y": 0}) for n in node_ids]
    pipe_edges = [PipelineEdge(source=f"{s}.out", target=f"{t}.in") for s, t in edges]
    return Pipeline(name="test", nodes=nodes, edges=pipe_edges)


def test_linear_order():
    p = _pipeline(("a", "b"), ("b", "c"))
    order = topological_sort(p)
    assert order.index("a") < order.index("b") < order.index("c")


def test_single_node():
    p = Pipeline(
        name="single",
        nodes=[PipelineNode(id="n1", tool="echo", params={}, position={"x": 0, "y": 0})],
        edges=[],
    )
    assert topological_sort(p) == ["n1"]


def test_cycle_raises():
    p = _pipeline(("a", "b"), ("b", "a"))
    with pytest.raises(ValueError, match="cycle"):
        topological_sort(p)


def test_upstream_outputs():
    edges = [PipelineEdge(source="n1.structure", target="n2.structure")]
    result = upstream_outputs("n2", edges)
    assert result == {"structure": "n1.structure"}
