from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.graph_index import GraphIndex


class ClientService:
    """Service for managing client profiles and scoring."""

    def __init__(self, graph_index: GraphIndex):
        self.graph_index = graph_index

    def calculate_profile_completeness(self, client_guid: str) -> dict[str, Any]:
        """
        Calculates the profile completeness score for a client.
        
        Formula: Score = Sum(Section_Weight * Section_Completeness)
        
        Sections:
        1. Holdings (35%): > 0 positions or watchlist items
        2. Mandate (35%): mandate_type (50%) + mandate_text (50%)
        3. Constraints (20%): esg_constrained is set
        4. Engagement (10%): primary_contact and alert_frequency exist
        
        Note: mandate_text is optional free-text field (0-5000 chars) that contributes
              independently to Mandate section. Both mandate_type and mandate_text can be
              present, one, or neither.
        
        Returns:
            Dict containing:
            - score: float (0.0 to 1.0)
            - details: breakdown of component scores
            - missing_fields: list of missing data points
        """
        query = """
        MATCH (c:Client {guid: $client_guid})
        OPTIONAL MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
        OPTIONAL MATCH (c)-[:HAS_PORTFOLIO]->(p:Portfolio)-[:HOLDS]->(h_inst)
        OPTIONAL MATCH (c)-[:HAS_WATCHLIST]->(w:Watchlist)-[:WATCHES]->(w_inst)
        OPTIONAL MATCH (cp)-[:EXCLUDES]->(ex)
        OPTIONAL MATCH (cp)-[:BENCHMARKED_TO]->(bm)
        WITH
            c,
            cp,
            count(DISTINCT h_inst) AS holding_count,
            count(DISTINCT w_inst) AS watchlist_count,
            count(DISTINCT ex) AS exclude_count,
            count(DISTINCT bm) AS benchmark_count
        RETURN {
            client_props: properties(c),
            profile_props: properties(cp),
            holding_count: holding_count,
            watchlist_count: watchlist_count,
            exclude_count: exclude_count,
            benchmark_count: benchmark_count
        } AS data
        """
        
        with self.graph_index._get_session() as session:
            result = session.run(query, client_guid=client_guid)
            record = result.single()
            if not record:
                # Client not found
                return {
                    "score": 0.0,
                    "details": {},
                    "error": "Client not found"
                }
            
            data = record["data"]
            
        return self._compute_score(data)

    def _compute_score(self, data: dict[str, Any]) -> dict[str, Any]:
        client_props = data.get("client_props") or {}
        profile_props = data.get("profile_props") or {}
        holding_count = data.get("holding_count", 0)
        watchlist_count = data.get("watchlist_count", 0)
        # exclude_count = data.get("exclude_count", 0) # Not used in basic scoring yet, but ready
        benchmark_count = data.get("benchmark_count", 0)  # noqa: F841 - reserved for future CPCS benchmark section
        
        # 1. Holdings Data (35%)
        # Critical for "Maintenance" coverage.
        has_holdings = (holding_count + watchlist_count) > 0
        score_holdings = 1.0 if has_holdings else 0.0
        
        # 2. Mandate Context (35%)
        # Critical for "Idea" generation.
        # Components: mandate_type (50%) + mandate_text (50%)
        # Both fields contribute independently to enable semantic document matching
        mandate_type = profile_props.get("mandate_type")
        mandate_text = profile_props.get("mandate_text")
        
        # mandate_type and mandate_text each contribute 50% (0.5) to mandate section
        score_mandate_type = 0.5 if mandate_type else 0.0
        score_mandate_text = 0.5 if (mandate_text and len(mandate_text.strip()) > 0) else 0.0
        
        score_mandate = score_mandate_type + score_mandate_text
        
        # 3. Constraints (20%)
        # Critical for filtering (Anti-Pitch).
        # Check: esg_constrained is explicitly set (True or False), not None/missing
        esg_constrained = profile_props.get("esg_constrained")
        score_constraints = 1.0 if esg_constrained is not None else 0.0
        
        # 4. Engagement (10%)
        # Context for delivery.
        # Check: primary_contact and alert_frequency exist (on Client or Profile)
        primary_contact = client_props.get("primary_contact") or profile_props.get("primary_contact")
        alert_frequency = client_props.get("alert_frequency") or profile_props.get("alert_frequency")
        score_engagement = 1.0 if primary_contact and alert_frequency else 0.0
        
        # Weighted Total
        total_score = (
            (score_holdings * 0.35) +
            (score_mandate * 0.35) +
            (score_constraints * 0.20) +
            (score_engagement * 0.10)
        )
        
        # Round to 2 decimals
        total_score = round(total_score, 2)
        
        return {
            "score": total_score,
            "breakdown": {
                "holdings": {
                    "score": round(score_holdings, 2),
                    "weight": 0.35,
                    "value": score_holdings * 0.35,
                    "details": {
                        "positions": holding_count,
                        "watchlist_items": watchlist_count
                    }
                },
                "mandate": {
                    "score": round(score_mandate, 2),
                    "weight": 0.35,
                    "value": score_mandate * 0.35,
                    "details": {
                        "mandate_type": bool(mandate_type),
                        "mandate_text": bool(mandate_text and len(mandate_text.strip()) > 0)
                    }
                },
                "constraints": {
                    "score": round(score_constraints, 2),
                    "weight": 0.20,
                    "value": score_constraints * 0.20,
                    "details": {
                        "esg_constrained_set": (esg_constrained is not None)
                    }
                },
                "engagement": {
                    "score": round(score_engagement, 2),
                    "weight": 0.10,
                    "value": score_engagement * 0.10,
                    "details": {
                        "primary_contact_set": bool(primary_contact),
                        "alert_frequency_set": bool(alert_frequency)
                    }
                }
            },
            "missing_fields": self._identify_missing_fields(
                has_holdings,
                mandate_type,
                mandate_text,
                esg_constrained,
                primary_contact,
                alert_frequency,
            )
        }

    def _identify_missing_fields(
        self,
        has_holdings,
        mandate_type,
        mandate_text,
        esg_constrained,
        primary_contact,
        alert_frequency,
    ) -> list[str]:
        missing = []
        if not has_holdings:
            missing.append("Holdings/Watchlist (No positions or watchlist items found)")
        if not mandate_type:
            missing.append("Mandate Type (client_profile.mandate_type)")
        if not (mandate_text and len(mandate_text.strip()) > 0):
            missing.append("Mandate Description (client_profile.mandate_text)")
        if esg_constrained is None:
            missing.append("ESG Constraints (client_profile.esg_constrained is null)")
        if not primary_contact:
            missing.append("Primary Contact (client.primary_contact or client_profile.primary_contact)")
        if not alert_frequency:
            missing.append("Alert Frequency (client.alert_frequency)")
        return missing
