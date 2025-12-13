"""Live LLM Data Capture for Model Tuning.

Captures data from live LLM runs to help tune:
1. Graph extraction prompts and scoring calibration
2. Embedding quality and semantic matching
3. Query result relevance

Usage:
    from test.fixtures.live_llm_capture import LiveDataCapture
    
    capture = LiveDataCapture()
    
    # Capture extraction results
    capture.record_extraction(
        doc_id="doc-123",
        title="Apple Q4 Earnings",
        content="...",
        extraction_result=result,
        expected_score=75,  # Optional ground truth
    )
    
    # Capture query results  
    capture.record_query(
        query_text="Apple iPhone sales",
        results=response.results,
        expected_titles=["Apple Q4 Earnings"],  # Optional ground truth
    )
    
    # Save captured data
    capture.save("test/tuning/run_20251210.json")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.prompts.graph_extraction import GraphExtractionResult


@dataclass
class ExtractionCapture:
    """Captured graph extraction data for analysis."""
    
    # Input
    doc_id: str
    title: str
    content: str
    content_length: int
    
    # LLM Output
    impact_score: int
    impact_tier: str
    event_type: Optional[str]
    event_confidence: Optional[float]
    instruments: list[dict[str, Any]]
    companies: list[str]
    summary: str
    raw_response: str
    
    # Ground Truth (optional - for evaluation)
    expected_score: Optional[int] = None
    expected_tier: Optional[str] = None
    expected_event: Optional[str] = None
    expected_instruments: Optional[list[str]] = None
    
    # Metrics
    score_delta: Optional[int] = None  # expected - actual
    tier_match: Optional[bool] = None
    event_match: Optional[bool] = None
    instrument_precision: Optional[float] = None
    instrument_recall: Optional[float] = None
    
    # Metadata
    timestamp: str = ""
    model: str = ""
    latency_ms: float = 0.0
    
    def compute_metrics(self) -> None:
        """Compute evaluation metrics against ground truth."""
        if self.expected_score is not None:
            self.score_delta = self.expected_score - self.impact_score
        
        if self.expected_tier is not None:
            self.tier_match = self.expected_tier == self.impact_tier
        
        if self.expected_event is not None:
            self.event_match = self.expected_event == self.event_type
        
        if self.expected_instruments is not None and self.instruments:
            extracted_tickers = {i["ticker"] for i in self.instruments}
            expected_set = set(self.expected_instruments)
            
            if extracted_tickers:
                self.instrument_precision = len(extracted_tickers & expected_set) / len(extracted_tickers)
            if expected_set:
                self.instrument_recall = len(extracted_tickers & expected_set) / len(expected_set)


@dataclass
class EmbeddingCapture:
    """Captured embedding data for analysis."""
    
    doc_id: str
    text: str
    text_length: int
    embedding_dims: int
    embedding_norm: float  # L2 norm
    
    # First few dimensions for quick inspection
    embedding_preview: list[float] = field(default_factory=list)
    
    timestamp: str = ""
    model: str = ""
    latency_ms: float = 0.0


@dataclass
class QueryCapture:
    """Captured query execution data for relevance tuning."""
    
    # Input
    query_text: str
    group_guids: list[str]
    n_results: int
    enable_graph_expansion: bool
    
    # Semantic search results
    semantic_results: list[dict[str, Any]] = field(default_factory=list)
    
    # Graph expansion results
    graph_expanded_docs: list[str] = field(default_factory=list)
    
    # Final combined results
    final_results: list[dict[str, Any]] = field(default_factory=list)
    
    # Ground Truth (optional)
    expected_titles: Optional[list[str]] = None
    
    # Relevance Metrics
    precision_at_k: Optional[dict[int, float]] = None  # P@1, P@3, P@5
    recall: Optional[float] = None
    mrr: Optional[float] = None  # Mean Reciprocal Rank
    ndcg: Optional[float] = None  # Normalized Discounted Cumulative Gain
    
    # Timing
    semantic_latency_ms: float = 0.0
    graph_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    
    timestamp: str = ""
    
    def compute_metrics(self) -> None:
        """Compute relevance metrics against ground truth."""
        if not self.expected_titles:
            return
            
        expected_set = set(self.expected_titles)
        result_titles = [r.get("title", "") for r in self.final_results]
        
        # Precision @ K
        self.precision_at_k = {}
        for k in [1, 3, 5]:
            if len(result_titles) >= k:
                hits = sum(1 for t in result_titles[:k] if t in expected_set)
                self.precision_at_k[k] = hits / k
        
        # Recall
        if expected_set:
            hits = sum(1 for t in result_titles if t in expected_set)
            self.recall = hits / len(expected_set)
        
        # MRR (Mean Reciprocal Rank)
        for i, title in enumerate(result_titles, 1):
            if title in expected_set:
                self.mrr = 1.0 / i
                break
        else:
            self.mrr = 0.0


@dataclass
class LiveDataCapture:
    """Collects data from live LLM runs for tuning analysis."""
    
    extractions: list[ExtractionCapture] = field(default_factory=list)
    embeddings: list[EmbeddingCapture] = field(default_factory=list)
    queries: list[QueryCapture] = field(default_factory=list)
    
    run_id: str = ""
    start_time: str = ""
    end_time: str = ""
    
    # Aggregate metrics
    total_tokens_used: int = 0
    total_api_calls: int = 0
    
    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if not self.start_time:
            self.start_time = datetime.now(timezone.utc).isoformat()
    
    def record_extraction(
        self,
        doc_id: str,
        title: str,
        content: str,
        extraction_result: GraphExtractionResult,
        expected_score: Optional[int] = None,
        expected_tier: Optional[str] = None,
        expected_event: Optional[str] = None,
        expected_instruments: Optional[list[str]] = None,
        model: str = "",
        latency_ms: float = 0.0,
    ) -> ExtractionCapture:
        """Record a graph extraction result."""
        
        primary_event = extraction_result.primary_event
        
        capture = ExtractionCapture(
            doc_id=doc_id,
            title=title,
            content=content,
            content_length=len(content),
            impact_score=extraction_result.impact_score,
            impact_tier=extraction_result.impact_tier,
            event_type=primary_event.event_type if primary_event else None,
            event_confidence=primary_event.confidence if primary_event else None,
            instruments=[i.to_dict() for i in extraction_result.instruments],
            companies=extraction_result.companies,
            summary=extraction_result.summary,
            raw_response=extraction_result.raw_response,
            expected_score=expected_score,
            expected_tier=expected_tier,
            expected_event=expected_event,
            expected_instruments=expected_instruments,
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=model,
            latency_ms=latency_ms,
        )
        
        capture.compute_metrics()
        self.extractions.append(capture)
        self.total_api_calls += 1
        
        return capture
    
    def record_embedding(
        self,
        doc_id: str,
        text: str,
        embedding: list[float],
        model: str = "",
        latency_ms: float = 0.0,
    ) -> EmbeddingCapture:
        """Record an embedding generation."""
        import math
        
        norm = math.sqrt(sum(x * x for x in embedding))
        
        capture = EmbeddingCapture(
            doc_id=doc_id,
            text=text,
            text_length=len(text),
            embedding_dims=len(embedding),
            embedding_norm=norm,
            embedding_preview=embedding[:10],  # First 10 dims
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=model,
            latency_ms=latency_ms,
        )
        
        self.embeddings.append(capture)
        self.total_api_calls += 1
        
        return capture
    
    def record_query(
        self,
        query_text: str,
        group_guids: list[str],
        results: list[Any],  # QueryResult objects
        n_results: int = 10,
        enable_graph_expansion: bool = True,
        expected_titles: Optional[list[str]] = None,
        semantic_latency_ms: float = 0.0,
        graph_latency_ms: float = 0.0,
        total_latency_ms: float = 0.0,
    ) -> QueryCapture:
        """Record a query execution."""
        
        final_results = []
        for r in results:
            final_results.append({
                "doc_guid": getattr(r, "doc_guid", ""),
                "title": getattr(r, "title", ""),
                "score": getattr(r, "score", 0.0),
                "semantic_score": getattr(r, "semantic_score", 0.0),
                "graph_boost": getattr(r, "graph_boost", 0.0),
                "recency_score": getattr(r, "recency_score", 0.0),
                "impact_tier": getattr(r, "impact_tier", ""),
            })
        
        capture = QueryCapture(
            query_text=query_text,
            group_guids=group_guids,
            n_results=n_results,
            enable_graph_expansion=enable_graph_expansion,
            final_results=final_results,
            expected_titles=expected_titles,
            semantic_latency_ms=semantic_latency_ms,
            graph_latency_ms=graph_latency_ms,
            total_latency_ms=total_latency_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        capture.compute_metrics()
        self.queries.append(capture)
        
        return capture
    
    def save(self, path: str | Path) -> None:
        """Save captured data to JSON file."""
        self.end_time = datetime.now(timezone.utc).isoformat()
        
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "run_id": self.run_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_api_calls": self.total_api_calls,
            "summary": self.get_summary(),
            "extractions": [asdict(e) for e in self.extractions],
            "embeddings": [asdict(e) for e in self.embeddings],
            "queries": [asdict(q) for q in self.queries],
        }
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        
        print(f"\n📊 Captured data saved to: {path}")
    
    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics of captured data."""
        summary: dict[str, Any] = {
            "total_extractions": len(self.extractions),
            "total_embeddings": len(self.embeddings),
            "total_queries": len(self.queries),
        }
        
        # Extraction metrics
        if self.extractions:
            scores = [e.impact_score for e in self.extractions]
            summary["extraction"] = {
                "avg_impact_score": sum(scores) / len(scores),
                "min_impact_score": min(scores),
                "max_impact_score": max(scores),
                "tier_distribution": {},
                "event_distribution": {},
            }
            
            for e in self.extractions:
                tier = e.impact_tier
                summary["extraction"]["tier_distribution"][tier] = \
                    summary["extraction"]["tier_distribution"].get(tier, 0) + 1
                
                if e.event_type:
                    summary["extraction"]["event_distribution"][e.event_type] = \
                        summary["extraction"]["event_distribution"].get(e.event_type, 0) + 1
            
            # Accuracy metrics (if ground truth provided)
            with_expected = [e for e in self.extractions if e.expected_score is not None]
            if with_expected:
                deltas = [abs(e.score_delta or 0) for e in with_expected]
                summary["extraction"]["mae_score"] = sum(deltas) / len(deltas)
                
                tier_matches = [e.tier_match for e in with_expected if e.tier_match is not None]
                if tier_matches:
                    summary["extraction"]["tier_accuracy"] = sum(tier_matches) / len(tier_matches)
        
        # Query metrics
        if self.queries:
            with_expected = [q for q in self.queries if q.expected_titles]
            if with_expected:
                mrrs = [q.mrr for q in with_expected if q.mrr is not None]
                if mrrs:
                    summary["query"] = {
                        "mean_mrr": sum(mrrs) / len(mrrs),
                    }
                    
                    # P@K
                    for k in [1, 3, 5]:
                        p_at_k = [q.precision_at_k.get(k, 0) for q in with_expected if q.precision_at_k]
                        if p_at_k:
                            summary["query"][f"mean_p@{k}"] = sum(p_at_k) / len(p_at_k)
        
        return summary
    
    def print_summary(self) -> None:
        """Print a human-readable summary."""
        summary = self.get_summary()
        
        print("\n" + "=" * 60)
        print("📊 LIVE LLM RUN SUMMARY")
        print("=" * 60)
        
        print(f"\nRun ID: {self.run_id}")
        print(f"Extractions: {summary['total_extractions']}")
        print(f"Embeddings: {summary['total_embeddings']}")
        print(f"Queries: {summary['total_queries']}")
        
        if "extraction" in summary:
            ext = summary["extraction"]
            print("\n📝 Extraction Stats:")
            print(f"   Impact Score: avg={ext['avg_impact_score']:.1f}, "
                  f"range=[{ext['min_impact_score']}, {ext['max_impact_score']}]")
            print(f"   Tier Distribution: {ext['tier_distribution']}")
            print(f"   Event Types: {ext['event_distribution']}")
            
            if "mae_score" in ext:
                print(f"   MAE (vs expected): {ext['mae_score']:.1f}")
            if "tier_accuracy" in ext:
                print(f"   Tier Accuracy: {ext['tier_accuracy']:.1%}")
        
        if "query" in summary:
            q = summary["query"]
            print("\n🔍 Query Relevance:")
            print(f"   MRR: {q.get('mean_mrr', 0):.3f}")
            for k in [1, 3, 5]:
                if f"mean_p@{k}" in q:
                    print(f"   P@{k}: {q[f'mean_p@{k}']:.3f}")
        
        print("=" * 60)


# =============================================================================
# Tuning Insights Extractor
# =============================================================================

def analyze_extraction_errors(captures: list[ExtractionCapture]) -> dict[str, Any]:
    """Analyze extraction errors to identify prompt improvement opportunities.
    
    Returns insights like:
    - Common over/under-scoring patterns
    - Event types frequently misclassified
    - Content patterns that confuse the model
    """
    insights: dict[str, Any] = {
        "over_scored": [],  # Score too high
        "under_scored": [],  # Score too low
        "tier_mismatches": [],
        "event_misclassified": [],
        "missing_instruments": [],
        "extra_instruments": [],
    }
    
    for cap in captures:
        if cap.score_delta is not None:
            if cap.score_delta > 15:  # Under-scored by >15 points
                insights["under_scored"].append({
                    "title": cap.title,
                    "expected": cap.expected_score,
                    "actual": cap.impact_score,
                    "delta": cap.score_delta,
                    "event_type": cap.event_type,
                })
            elif cap.score_delta < -15:  # Over-scored by >15 points
                insights["over_scored"].append({
                    "title": cap.title,
                    "expected": cap.expected_score,
                    "actual": cap.impact_score,
                    "delta": cap.score_delta,
                    "event_type": cap.event_type,
                })
        
        if cap.tier_match is False:
            insights["tier_mismatches"].append({
                "title": cap.title,
                "expected_tier": cap.expected_tier,
                "actual_tier": cap.impact_tier,
                "score": cap.impact_score,
            })
        
        if cap.event_match is False:
            insights["event_misclassified"].append({
                "title": cap.title,
                "expected_event": cap.expected_event,
                "actual_event": cap.event_type,
                "confidence": cap.event_confidence,
            })
        
        if cap.instrument_recall is not None and cap.instrument_recall < 1.0:
            insights["missing_instruments"].append({
                "title": cap.title,
                "expected": cap.expected_instruments,
                "extracted": [i["ticker"] for i in cap.instruments],
                "recall": cap.instrument_recall,
            })
        
        if cap.instrument_precision is not None and cap.instrument_precision < 1.0:
            insights["extra_instruments"].append({
                "title": cap.title,
                "expected": cap.expected_instruments,
                "extracted": [i["ticker"] for i in cap.instruments],
                "precision": cap.instrument_precision,
            })
    
    return insights


def generate_tuning_recommendations(insights: dict[str, Any]) -> list[str]:
    """Generate actionable recommendations from error analysis."""
    recommendations = []
    
    if insights["over_scored"]:
        recommendations.append(
            f"🔴 Over-scoring detected in {len(insights['over_scored'])} docs. "
            "Consider adding calibration examples for routine news in prompt."
        )
        
        # Check for patterns
        event_types = [e["event_type"] for e in insights["over_scored"]]
        from collections import Counter
        common = Counter(event_types).most_common(2)
        if common:
            recommendations.append(
                f"   → Most over-scored event types: {common}"
            )
    
    if insights["under_scored"]:
        recommendations.append(
            f"🔵 Under-scoring detected in {len(insights['under_scored'])} docs. "
            "Consider adding examples of high-impact events in prompt."
        )
    
    if insights["tier_mismatches"]:
        recommendations.append(
            f"⚠️  Tier mismatches in {len(insights['tier_mismatches'])} docs. "
            "Review tier boundary thresholds in prompt."
        )
    
    if insights["missing_instruments"]:
        recommendations.append(
            f"📉 Missing instruments in {len(insights['missing_instruments'])} docs. "
            "Model may need examples of indirect mentions or ticker recognition."
        )
    
    if insights["extra_instruments"]:
        recommendations.append(
            f"📈 Extra instruments in {len(insights['extra_instruments'])} docs. "
            "Model may be too aggressive - add examples of what NOT to extract."
        )
    
    return recommendations
