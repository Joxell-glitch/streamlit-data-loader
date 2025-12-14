from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from src.config.models import Settings
from src.core.logging import get_logger


logger = get_logger(__name__)


@dataclass
class Edge:
    base: str
    quote: str
    pair: str


@dataclass
class Triangle:
    id: int
    assets: Tuple[str, str, str]
    edges: Tuple[Edge, Edge, Edge]


class MarketGraph:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.edges: List[Edge] = []
        self.triangles: List[Triangle] = []
        self.last_build_stats: Dict[str, int] = {}
        self.last_triangle_stats: Dict[str, int] = {}

    def build_from_spot_meta(self, spot_meta: dict, max_sample_edges: int = 10) -> None:
        pairs = spot_meta.get("universe", [])
        quote_asset = self.settings.trading.quote_asset
        whitelist = set(a.upper() for a in self.settings.trading.whitelist)
        blacklist = set(a.upper() for a in self.settings.trading.blacklist)
        is_hyperliquid = "hyperliquid" in (getattr(self.settings.api, "rest_base", "") or "").lower()

        markets_total = len(pairs)
        markets_active = sum(1 for entry in pairs if entry.get("enabled", True))
        skipped_missing_base = 0
        skipped_whitelist = 0
        skipped_blacklist = 0
        used_pairs = set()

        for entry in pairs:
            pair_name = entry.get("pair")
            if is_hyperliquid:
                symbol = entry.get("name") or entry.get("coin") or entry.get("base") or entry.get("symbol") or entry.get("pair")
                if not symbol:
                    skipped_missing_base += 1
                    continue
                base = symbol.upper()
                quote = quote_asset.upper()
            else:
                base = entry.get("base") or entry.get("coin")
                quote = entry.get("quote") or quote_asset
                if not base:
                    skipped_missing_base += 1
                    continue
                base = base.upper()
                quote = quote.upper()
                if whitelist and base not in whitelist and quote not in whitelist:
                    skipped_whitelist += 1
                    continue
            if base in blacklist or quote in blacklist:
                skipped_blacklist += 1
                continue
            pair_name = pair_name or f"{base}/{quote}"
            used_pairs.add(pair_name)
            if is_hyperliquid:
                logger.info("[GRAPH][INFO] hyperliquid_market accepted base=%s quote=%s", base, quote)
            self.edges.append(Edge(base=base, quote=quote, pair=pair_name))
            self.edges.append(Edge(base=quote, quote=base, pair=pair_name))

        self.triangles = self._enumerate_triangles()

        nodes_count = len(self.assets)
        edges_count = len(self.edges)
        max_sample_edges = min(max_sample_edges, 10)
        sample_edges = [(e.base, e.quote) for e in self.edges[:max_sample_edges]]

        self.last_build_stats = {
            "markets_total": markets_total,
            "markets_active": markets_active,
            "markets_used": len(used_pairs),
            "nodes": nodes_count,
            "edges": edges_count,
            "skipped_missing_base": skipped_missing_base,
            "skipped_whitelist": skipped_whitelist,
            "skipped_blacklist": skipped_blacklist,
        }

        logger.info(
            "[GRAPH] markets_total=%s markets_active=%s markets_used=%s nodes=%s edges=%s",  # noqa: E501
            markets_total,
            markets_active,
            len(used_pairs),
            nodes_count,
            edges_count,
        )
        logger.info(
            "[GRAPH] sample_edges=%s skipped_missing_base=%s skipped_whitelist=%s skipped_blacklist=%s",
            sample_edges,
            skipped_missing_base,
            skipped_whitelist,
            skipped_blacklist,
        )

    def _enumerate_triangles(self) -> List[Triangle]:
        triangles: List[Triangle] = []
        assets = list(self.assets)
        edge_lookup: Dict[Tuple[str, str], Edge] = {(e.base, e.quote): e for e in self.edges}
        nodes_count = len(assets)
        edges_count = len(self.edges)
        logger.info("[TRI_ENUM] start nodes=%s edges=%s", nodes_count, edges_count)
        tid = 0
        skipped_same_node = 0
        skipped_missing_edge = 0
        for i, a in enumerate(assets):
            for j, b in enumerate(assets):
                if j == i:
                    skipped_same_node += 1
                    continue
                for k, c in enumerate(assets):
                    if k in {i, j}:
                        skipped_same_node += 1
                        continue
                    has_ab = (a, b) in edge_lookup
                    has_bc = (b, c) in edge_lookup
                    has_ca = (c, a) in edge_lookup
                    if has_ab and has_bc and has_ca:
                        tri = Triangle(
                            id=tid,
                            assets=(a, b, c),
                            edges=(edge_lookup[(a, b)], edge_lookup[(b, c)], edge_lookup[(c, a)]),
                        )
                        triangles.append(tri)
                        tid += 1
                    else:
                        skipped_missing_edge += 1

        self.last_triangle_stats = {
            "triangles_total": len(triangles),
            "skipped_missing_edge": skipped_missing_edge,
            "skipped_same_node": skipped_same_node,
        }
        logger.info(
            "[TRI_ENUM] triangles_total=%s skipped_missing_edge=%s skipped_same_node=%s",
            len(triangles),
            skipped_missing_edge,
            skipped_same_node,
        )
        if not triangles:
            reasons = []
            if nodes_count == 0:
                reasons.append("nodes=0")
            if edges_count == 0:
                reasons.append("edges=0")
            if self.last_build_stats.get("markets_active") == 0:
                reasons.append("markets_active=0")
            if skipped_missing_edge > 0 and edges_count > 0:
                reasons.append("missing_edge_paths")
            if not reasons:
                reasons.append("unknown")
            logger.info("[TRI_ENUM] triangles_zero_reasons=%s", ",".join(reasons))
        return triangles

    @property
    def assets(self) -> Set[str]:
        return {e.base for e in self.edges} | {e.quote for e in self.edges}
