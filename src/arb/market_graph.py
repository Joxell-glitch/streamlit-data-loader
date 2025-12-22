from __future__ import annotations

from collections import Counter
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

    def _log_triangle_assets(self) -> None:
        triangle_assets = {edge.base for tri in self.triangles for edge in tri.edges}
        logger.info(
            "[TRIANGLE_ASSETS] triangles=%d unique_assets=%d",
            len(self.triangles),
            len(triangle_assets),
        )
        if not self.triangles:
            reason = self.last_triangle_stats.get("triangles_zero_reason") or "unknown"
            logger.warning("[TRIANGLE_ASSETS] triangles_total=0 reason=%s", reason)

    def build_from_spot_meta(self, spot_meta: dict, max_sample_edges: int = 10) -> None:
        self.edges = []
        self.triangles = []
        pairs = spot_meta.get("universe", [])
        quote_asset = self.settings.trading.quote_asset
        whitelist = set(a.upper() for a in self.settings.trading.whitelist)
        blacklist = set(a.upper() for a in self.settings.trading.blacklist)
        is_hyperliquid = (
            "hyperliquid" in (getattr(self.settings.api, "rest_base", "") or "").lower()
            or ("tokens" in spot_meta and any(isinstance(u.get("tokens"), list) and len(u.get("tokens")) == 2 for u in spot_meta.get("universe", [])))
        )

        markets_total = len(pairs)
        markets_active = sum(1 for entry in pairs if entry.get("enabled", True))
        skipped_missing_base = 0
        skipped_whitelist = 0
        skipped_blacklist = 0
        used_pairs = set()
        quote_counter: Counter[str] = Counter()
        base_counter: Counter[str] = Counter()
        cross_quote_examples: List[str] = []
        token_map: Dict[int, str] = {}

        if is_hyperliquid:
            tokens_sources = spot_meta.get("tokens", [])
            spot_meta_data = spot_meta.get("spotMeta")
            if isinstance(spot_meta_data, dict):
                tokens_sources = tokens_sources + spot_meta_data.get("tokens", [])
            for token in tokens_sources:
                idx = token.get("index")
                name = token.get("name")
                if idx is not None and name:
                    token_map[idx] = str(name).upper()
        is_hyperliquid_spot = is_hyperliquid and bool(token_map)

        for entry in pairs:
            if is_hyperliquid_spot:
                entry_tokens = entry.get("tokens")
                if not entry_tokens or len(entry_tokens) != 2:
                    skipped_missing_base += 1
                    continue
                base_id, quote_id = entry_tokens
                base = token_map.get(base_id)
                quote = token_map.get(quote_id)
                if not base or not quote:
                    skipped_missing_base += 1
                    continue
                if whitelist and base not in whitelist and quote not in whitelist:
                    skipped_whitelist += 1
                    continue
            else:
                base = entry.get("base") or entry.get("coin")
                if is_hyperliquid and not is_hyperliquid_spot:
                    base = base or entry.get("name") or entry.get("symbol")
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
            pair_name = entry.get("pair")
            if is_hyperliquid_spot and entry.get("isCanonical"):
                entry_name = entry.get("name")
                if isinstance(entry_name, str) and "/" in entry_name:
                    pair_name = entry_name.upper()
            pair_name = pair_name or f"{base}/{quote}"
            used_pairs.add(pair_name)
            base_counter[base] += 1
            quote_counter[quote] += 1
            if quote != "USD" and len(cross_quote_examples) < 20:
                market_kind = entry.get("kind") or "unknown"
                cross_quote_examples.append(
                    f"{pair_name}|base={base} quote={quote} isPerp=False isSpot=True kind={market_kind}"
                )
            self.edges.append(Edge(base=base, quote=quote, pair=pair_name))
            self.edges.append(Edge(base=quote, quote=base, pair=pair_name))

        stable_quotes = {"USD", "USDC", "USDH", "USDE", "USDT0"}
        unique_quotes = set(quote_counter.keys())
        no_cross_spot_reason = None
        if is_hyperliquid and unique_quotes and unique_quotes.issubset(stable_quotes):
            no_cross_spot_reason = "no_cross_quotes_on_spot"
            self.last_triangle_stats["triangles_zero_reason"] = no_cross_spot_reason

        self.triangles = self._enumerate_triangles()
        if no_cross_spot_reason:
            self.last_triangle_stats["triangles_zero_reason"] = no_cross_spot_reason

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
        logger.info(
            "[GRAPH_DIAG] quotes_top10=%s bases_top10=%s counts(total=%s active=%s used=%s)",
            quote_counter.most_common(10),
            base_counter.most_common(10),
            markets_total,
            markets_active,
            len(used_pairs),
        )
        logger.info("[GRAPH_DIAG] cross_quote_examples=%s", cross_quote_examples)
        self._log_triangle_assets()

    def build_from_perp_meta(self, perp_meta: dict, max_sample_edges: int = 10) -> None:
        self.edges = []
        self.triangles = []
        pairs = perp_meta.get("universe", [])
        quote_asset = "USD"
        whitelist = set(a.upper() for a in self.settings.trading.whitelist)
        blacklist = set(a.upper() for a in self.settings.trading.blacklist)

        markets_total = len(pairs)
        markets_active = sum(1 for entry in pairs if entry.get("enabled", True))
        skipped_missing_base = 0
        skipped_whitelist = 0
        skipped_blacklist = 0
        used_pairs = set()
        quote_counter: Counter[str] = Counter()
        base_counter: Counter[str] = Counter()

        for entry in pairs:
            symbol = (
                entry.get("name")
                or entry.get("symbol")
                or entry.get("coin")
                or entry.get("base")
            )
            if not symbol:
                skipped_missing_base += 1
                continue
            base = symbol.upper()
            quote = quote_asset
            if whitelist and base not in whitelist and quote not in whitelist:
                skipped_whitelist += 1
                continue
            if base in blacklist or quote in blacklist:
                skipped_blacklist += 1
                continue
            pair_name = f"{base}-PERP"
            used_pairs.add(pair_name)
            base_counter[base] += 1
            quote_counter[quote] += 1
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
            "[GRAPH] markets_total=%s markets_active=%s markets_used=%s nodes=%s edges=%s",
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
        logger.info(
            "[GRAPH_DIAG] quotes_top10=%s bases_top10=%s counts(total=%s active=%s used=%s)",
            quote_counter.most_common(10),
            base_counter.most_common(10),
            markets_total,
            markets_active,
            len(used_pairs),
        )
        logger.info("[GRAPH_DIAG] cross_quote_examples=%s", [])
        self._log_triangle_assets()

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
            out_degree: Counter[str] = Counter()
            in_degree: Counter[str] = Counter()
            total_degree: Counter[str] = Counter()
            for edge in self.edges:
                out_degree[edge.base] += 1
                in_degree[edge.quote] += 1
                total_degree[edge.base] += 1
                total_degree[edge.quote] += 1
            total_edges = len(self.edges)
            top_node, top_degree = (total_degree.most_common(1)[0] if total_degree else ("", 0))
            star_like = total_edges > 0 and (top_degree / total_edges) > 0.8
            logger.info(
                "[TRI_ENUM_DIAG] out_top10=%s in_top10=%s star_like=%s top_node=%s",
                out_degree.most_common(10),
                in_degree.most_common(10),
                star_like,
                top_node,
            )
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
            reason_str = ",".join(reasons)
            logger.info("[TRI_ENUM] triangles_zero_reasons=%s", reason_str)
            if self.last_triangle_stats.get("triangles_zero_reason") == "no_cross_quotes_on_spot":
                self.last_triangle_stats["triangles_zero_reason"] = "no_cross_quotes_on_spot"
            else:
                self.last_triangle_stats["triangles_zero_reason"] = reason_str
        return triangles

    @property
    def assets(self) -> Set[str]:
        return {e.base for e in self.edges} | {e.quote for e in self.edges}
