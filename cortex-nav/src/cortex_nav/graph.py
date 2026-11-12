"""The verified tool-call graph: an agent's action space is exactly its edges.

A forbidden transition is ABSENT from the edge set. It is never present with a negative
weight, so there is nothing for a planner or a policy to "outweigh".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
import json
import math
from pathlib import Path
from typing import Any

from .canonical import ZERO_ADDRESS, address_bytes, leaf, node_id, selector_for

MAX_RISK_WEIGHT_BPS = 10_000


@dataclass(frozen=True)
class Edge:
    """One allowed transition.

    `from_node`, `relation`, `to_node`, `target`, `target_selector` and `risk_weight_bps` are
    committed on-chain through `leaf`. `grounded` and `r_task` are off-chain annotations: they
    are NOT part of the leaf, so the Merkle root does not vouch for them.
    """

    from_node: bytes
    relation: bytes
    to_node: bytes
    target: bytes
    target_selector: bytes
    risk_weight_bps: int
    grounded: bool
    r_task: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", address_bytes(self.target))
        if isinstance(self.risk_weight_bps, bool) or not isinstance(self.risk_weight_bps, int):
            raise TypeError("risk_weight_bps must be an int")
        if not 0 <= self.risk_weight_bps <= MAX_RISK_WEIGHT_BPS:
            raise ValueError(f"risk_weight_bps must be in [0, {MAX_RISK_WEIGHT_BPS}]")
        if not isinstance(self.grounded, bool):
            raise TypeError("grounded must be a bool")
        r_task = float(self.r_task)
        if not math.isfinite(r_task) or r_task < 0.0:
            raise ValueError("r_task must be finite and non-negative; remove a forbidden edge instead of penalizing it")
        object.__setattr__(self, "r_task", r_task)
        # Computing the leaf validates the remaining committed fields.
        _ = self.leaf

    @cached_property
    def leaf(self) -> bytes:
        return leaf(
            self.from_node, self.relation, self.to_node, self.target, self.target_selector, self.risk_weight_bps
        )


class ToolCallGraph:
    """An immutable set of edges with a deterministic order.

    `edges` is sorted by leaf, so it depends only on the edge set, not on insertion order.
    An action index is an index into `edges` and is stable for a given edge set (and so for
    a given root); adding or removing an edge yields a new graph, root and index space.
    """

    def __init__(self, edges: Iterable[Edge]) -> None:
        ordered = sorted(edges, key=lambda e: e.leaf)
        by_leaf: dict[bytes, Edge] = {}
        out: dict[bytes, list[Edge]] = {}
        for edge in ordered:
            if not isinstance(edge, Edge):
                raise TypeError("ToolCallGraph takes Edge instances")
            if edge.leaf in by_leaf:
                raise ValueError("duplicate edge leaf 0x" + edge.leaf.hex())
            by_leaf[edge.leaf] = edge
            out.setdefault(edge.from_node, []).append(edge)
        self._edges: tuple[Edge, ...] = tuple(ordered)
        self._by_leaf = by_leaf
        self._out = {node: tuple(group) for node, group in out.items()}

    @property
    def edges(self) -> tuple[Edge, ...]:
        return self._edges

    def out_edges(self, node: bytes) -> tuple[Edge, ...]:
        """Edges leaving `node`, in `edges` order. Empty for a dead end or an unknown node."""
        return self._out.get(bytes(node), ())

    def index_of(self, edge: Edge) -> int:
        """The action index of `edge`. Raises `KeyError` if its leaf is not in the graph."""
        if edge.leaf not in self._by_leaf:
            raise KeyError("edge is not in the graph: 0x" + edge.leaf.hex())
        return self._edges.index(self._by_leaf[edge.leaf])

    def __contains__(self, edge: object) -> bool:
        """Membership is by exact leaf, i.e. by every on-chain-committed field."""
        return isinstance(edge, Edge) and edge.leaf in self._by_leaf

    def __len__(self) -> int:
        return len(self._edges)


def toolgraph_from_spec(spec: dict[str, Any]) -> ToolCallGraph:
    """Build a graph from the JSON layout used by `tests/fixtures/toy_toolgraph.json`.

    Each edge names its nodes and relation by canonical string. An edge with an
    `onchain_signature` is bound to `spec["onchain_target"]` and that signature's selector;
    an edge without one is off-chain only (zero address, zero selector).
    """
    onchain_target = spec.get("onchain_target", ZERO_ADDRESS)
    edges = []
    for raw in spec["edges"]:
        signature = raw.get("onchain_signature")
        edges.append(
            Edge(
                from_node=node_id(raw["from"]),
                relation=node_id(raw["relation"]),
                to_node=node_id(raw["to"]),
                target=onchain_target if signature is not None else ZERO_ADDRESS,
                target_selector=selector_for(signature),
                risk_weight_bps=raw["risk_weight_bps"],
                grounded=raw["grounded"],
                r_task=raw["r_task"],
            )
        )
    return ToolCallGraph(edges)


def load_toolgraph(path: str | Path) -> ToolCallGraph:
    return toolgraph_from_spec(json.loads(Path(path).read_text(encoding="utf-8")))
