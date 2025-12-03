from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from src.config.models import Settings


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

    def build_from_spot_meta(self, spot_meta: dict) -> None:
        pairs = spot_meta.get("universe", [])
        quote_asset = self.settings.trading.quote_asset
        whitelist = set(a.upper() for a in self.settings.trading.whitelist)
        blacklist = set(a.upper() for a in self.settings.trading.blacklist)

        for entry in pairs:
            base = entry.get("base") or entry.get("coin")
            quote = entry.get("quote") or quote_asset
            if not base:
                continue
            base = base.upper()
            quote = quote.upper()
            if whitelist and base not in whitelist and quote not in whitelist:
                continue
            if base in blacklist or quote in blacklist:
                continue
            pair_name = entry.get("pair") or f"{base}/{quote}"
            self.edges.append(Edge(base=base, quote=quote, pair=pair_name))
            self.edges.append(Edge(base=quote, quote=base, pair=pair_name))

        self.triangles = self._enumerate_triangles()

    def _enumerate_triangles(self) -> List[Triangle]:
        triangles: List[Triangle] = []
        assets = list(self.assets)
        edge_lookup: Dict[Tuple[str, str], Edge] = {(e.base, e.quote): e for e in self.edges}
        tid = 0
        for i, a in enumerate(assets):
            for j, b in enumerate(assets):
                if j == i:
                    continue
                for k, c in enumerate(assets):
                    if k in {i, j}:
                        continue
                    if (a, b) in edge_lookup and (b, c) in edge_lookup and (c, a) in edge_lookup:
                        tri = Triangle(
                            id=tid,
                            assets=(a, b, c),
                            edges=(edge_lookup[(a, b)], edge_lookup[(b, c)], edge_lookup[(c, a)]),
                        )
                        triangles.append(tri)
                        tid += 1
        return triangles

    @property
    def assets(self) -> Set[str]:
        return {e.base for e in self.edges} | {e.quote for e in self.edges}
