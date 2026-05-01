"""DAG utilities: build adjacency list, topological sort, cycle detection."""
from collections import defaultdict, deque

from app.models.pipeline import Pipeline, PipelineEdge


def _node_id_from_port(port_ref: str) -> str:
    """'n1.backbone' → 'n1'"""
    return port_ref.split(".")[0]


def build_adjacency(pipeline: Pipeline) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = defaultdict(list)
    for node in pipeline.nodes:
        adj[node.id]  # ensure every node is present
    for edge in pipeline.edges:
        src = _node_id_from_port(edge.source)
        tgt = _node_id_from_port(edge.target)
        adj[src].append(tgt)
    return dict(adj)


def topological_sort(pipeline: Pipeline) -> list[str]:
    """Return nodes in execution order. Raises ValueError on cycles."""
    adj = build_adjacency(pipeline)
    in_degree: dict[str, int] = {n: 0 for n in adj}
    for neighbors in adj.values():
        for nb in neighbors:
            in_degree[nb] += 1

    queue = deque(n for n, d in in_degree.items() if d == 0)
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for nb in adj[node]:
            in_degree[nb] -= 1
            if in_degree[nb] == 0:
                queue.append(nb)

    if len(order) != len(adj):
        raise ValueError("Pipeline contains a cycle")
    return order


def upstream_outputs(
    node_id: str, edges: list[PipelineEdge]
) -> list[tuple[str, str]]:
    """Return [(input_port, 'upstream_node_id.output_port'), ...] for a given node.

    A list (not dict) so that multiple edges to the same input port (e.g. two
    nodes both wired to the generic 'in' handle) are all included.
    """
    result = []
    for edge in edges:
        if _node_id_from_port(edge.target) == node_id:
            input_port = edge.target.split(".", 1)[1] if "." in edge.target else edge.target
            result.append((input_port, edge.source))
    return result
