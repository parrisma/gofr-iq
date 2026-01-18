"""
Client Profiler - Semantic IPS Analysis

Loads Investment Policy Statements and creates semantic embeddings for:
- ESG preferences and exclusions
- Sector/thematic preferences
- News priority signals
- Mandate constraints

Used by feed reranking to apply client-specific intelligence filtering.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ClientProfile:
    """Semantic representation of client investment preferences"""
    client_guid: str
    client_name: str
    archetype: str
    
    # Trust and risk
    min_trust_level: int
    risk_tolerance: str
    alert_threshold: float
    
    # Semantic filters
    prohibited_sectors: List[str]
    esg_exclusions: List[str]
    positive_themes: List[str]
    news_priority: List[str]
    
    # Full IPS for context
    ips_summary: str
    
    @classmethod
    def from_ips_json(cls, ips_path: Path) -> 'ClientProfile':
        """Load profile from IPS JSON file"""
        with open(ips_path, 'r') as f:
            ips_data = json.load(f)
        
        # Extract trust level from text requirement
        trust_text = ips_data.get('trust_requirement', '')
        if 'trust level 8+' in trust_text.lower():
            min_trust = 8
        elif 'trust level 2+' in trust_text.lower():
            min_trust = 2
        elif 'trust level 1+' in trust_text.lower():
            min_trust = 1
        else:
            min_trust = 5  # Default
        
        # Create semantic summary
        ips_summary = f"""
Investment Profile for {ips_data['client_name']}:
Objective: {ips_data['primary_objective']}
Risk Tolerance: {ips_data['risk_tolerance']}
Time Horizon: {ips_data['time_horizon']}
ESG Policy: {ips_data['esg_policy']}
Trust Requirement: {ips_data['trust_requirement']}
News Priorities: {', '.join(ips_data['news_priority'])}
Positive Themes: {', '.join(ips_data['positive_themes'])}
""".strip()
        
        return cls(
            client_guid=ips_data['client_guid'],
            client_name=ips_data['client_name'],
            archetype=ips_data['archetype'],
            min_trust_level=min_trust,
            risk_tolerance=ips_data['risk_tolerance'],
            alert_threshold=ips_data['alert_threshold'],
            prohibited_sectors=ips_data['prohibited_sectors'],
            esg_exclusions=ips_data['esg_exclusions'],
            positive_themes=ips_data['positive_themes'],
            news_priority=ips_data['news_priority'],
            ips_summary=ips_summary
        )
    
    def should_exclude_sector(self, sector: str) -> bool:
        """Check if sector is prohibited"""
        sector_lower = sector.lower()
        return any(
            prohibited.lower() in sector_lower or sector_lower in prohibited.lower()
            for prohibited in self.prohibited_sectors
        )
    
    def has_esg_concern(self, company_name: str, description: str) -> bool:
        """Check if document mentions ESG exclusion topics"""
        text = f"{company_name} {description}".lower()
        return any(
            exclusion.lower() in text
            for exclusion in self.esg_exclusions
        )
    
    def theme_alignment_score(self, document_text: str) -> float:
        """Calculate how well document aligns with positive themes (0-1)"""
        if not self.positive_themes:
            return 0.5  # Neutral if no themes specified
        
        text_lower = document_text.lower()
        matches = sum(
            1 for theme in self.positive_themes
            if any(word in text_lower for word in theme.lower().split())
        )
        return min(matches / len(self.positive_themes), 1.0)
    
    def event_priority_score(self, event_type: str) -> float:
        """Score event type importance (0-1) based on news priorities"""
        if not self.news_priority:
            return 0.5
        
        event_lower = event_type.lower()
        for i, priority in enumerate(self.news_priority):
            priority_lower = priority.lower()
            if event_lower in priority_lower or priority_lower in event_lower:
                # Higher priority = higher score (first item = 1.0, last = ~0.5)
                return 1.0 - (i / len(self.news_priority) * 0.5)
        
        return 0.3  # Not in priority list = low score


class ClientProfiler:
    """
    Loads and manages client IPS profiles
    
    Supports two modes:
    1. File-based (simulation): Load from JSON files
    2. Runtime (production): Parse IPS from supplied JSON dict
    """
    
    def __init__(self, ips_directory: Optional[Path] = None):
        if ips_directory is None:
            ips_directory = Path(__file__).parent / "client_ips"
        
        self.ips_directory = ips_directory
        self.profiles: Dict[str, ClientProfile] = {}
        self._load_profiles()
    
    def _load_profiles(self):
        """Load all IPS files from directory (simulation mode)"""
        if not self.ips_directory.exists():
            logger.warning(f"IPS directory not found: {self.ips_directory}")
            return
        
        for ips_file in self.ips_directory.glob("ips_*.json"):
            try:
                profile = ClientProfile.from_ips_json(ips_file)
                self.profiles[profile.client_guid] = profile
                logger.info(f"Loaded profile: {profile.client_name} (trust={profile.min_trust_level})")
            except Exception as e:
                logger.error(f"Failed to load {ips_file}: {e}")
    
    def get_profile(
        self, 
        client_guid: str,
        ips_json: Optional[Dict] = None
    ) -> Optional[ClientProfile]:
        """
        Get profile for client
        
        Args:
            client_guid: Client identifier
            ips_json: Optional IPS JSON dict (production mode)
                     If provided, creates profile on-the-fly
                     If not provided, loads from file cache
        
        Returns:
            ClientProfile or None
        """
        # Production mode: IPS supplied at query time
        if ips_json:
            return self._profile_from_dict(ips_json)
        
        # Simulation mode: Load from file cache
        return self.profiles.get(client_guid)
    
    def _profile_from_dict(self, ips_data: Dict) -> ClientProfile:
        """Create profile from IPS dictionary (production mode)"""
        # Extract trust level from text requirement
        trust_text = ips_data.get('trust_requirement', '')
        if 'trust level 8+' in trust_text.lower():
            min_trust = 8
        elif 'trust level 2+' in trust_text.lower():
            min_trust = 2
        elif 'trust level 1+' in trust_text.lower():
            min_trust = 1
        else:
            min_trust = 5  # Default
        
        # Create semantic summary
        ips_summary = f"""
Investment Profile for {ips_data['client_name']}:
Objective: {ips_data['primary_objective']}
Risk Tolerance: {ips_data['risk_tolerance']}
Time Horizon: {ips_data['time_horizon']}
ESG Policy: {ips_data['esg_policy']}
Trust Requirement: {ips_data['trust_requirement']}
News Priorities: {', '.join(ips_data['news_priority'])}
Positive Themes: {', '.join(ips_data['positive_themes'])}
""".strip()
        
        return ClientProfile(
            client_guid=ips_data['client_guid'],
            client_name=ips_data['client_name'],
            archetype=ips_data['archetype'],
            min_trust_level=min_trust,
            risk_tolerance=ips_data['risk_tolerance'],
            alert_threshold=ips_data['alert_threshold'],
            prohibited_sectors=ips_data['prohibited_sectors'],
            esg_exclusions=ips_data['esg_exclusions'],
            positive_themes=ips_data['positive_themes'],
            news_priority=ips_data['news_priority'],
            ips_summary=ips_summary
        )
    
    def apply_filters(
        self,
        client_guid: str,
        documents: List[Dict],
        ips_json: Optional[Dict] = None,
        sector_field: str = "sector",
        company_field: str = "company_name",
        description_field: str = "summary"
    ) -> List[Dict]:
        """
        Apply IPS-based filters to documents
        
        Args:
            client_guid: Client identifier
            documents: List of document dicts
            ips_json: Optional IPS JSON (production mode)
            sector_field: Key for sector in document dict
            company_field: Key for company name
            description_field: Key for description/summary
        
        Returns:
            Filtered list with documents that pass client's IPS constraints
        """
        profile = self.get_profile(client_guid, ips_json=ips_json)
        if not profile:
            logger.warning(f"No profile found for {client_guid}, returning unfiltered")
            return documents
        
        filtered = []
        for doc in documents:
            # Check trust level
            trust_level = doc.get("trust_level", 10)  # Default to max trust if not specified
            if trust_level < profile.min_trust_level:
                logger.debug(f"Filtered {doc.get('title')}: trust {trust_level} < min {profile.min_trust_level}")
                continue
            
            # Check sector exclusions
            sector = doc.get(sector_field, "")
            if sector and profile.should_exclude_sector(sector):
                logger.debug(f"Filtered {doc.get('title')}: prohibited sector {sector}")
                continue
            
            # Check ESG exclusions
            company = doc.get(company_field, "")
            description = doc.get(description_field, "")
            if profile.has_esg_concern(company, description):
                logger.debug(f"Filtered {doc.get('title')}: ESG concern")
                continue
            
            filtered.append(doc)
        
        logger.info(f"IPS filtering: {len(documents)} → {len(filtered)} documents for {profile.client_name}")
        return filtered
    
    def rerank_documents(
        self,
        client_guid: str,
        documents: List[Dict],
        ips_json: Optional[Dict] = None,
        text_field: str = "summary",
        event_type_field: str = "primary_event",
        base_score_field: str = "feed_rank"
    ) -> List[Dict]:
        """
        Rerank documents based on IPS preferences
        
        Args:
            client_guid: Client identifier
            documents: List of document dicts
            ips_json: Optional IPS JSON (production mode)
            text_field: Field containing text for theme matching
            event_type_field: Field containing event type
            base_score_field: Field containing original score
        
        Adjusts scores based on:
        - Theme alignment (positive themes boost)
        - Event type priority
        - ESG alignment
        
        Returns documents sorted by adjusted score
        """
        profile = self.get_profile(client_guid, ips_json=ips_json)
        if not profile:
            return documents
        
        reranked = []
        for doc in documents:
            base_score = doc.get(base_score_field, 50.0)
            
            # Theme alignment boost (+0 to +20 points)
            text = doc.get(text_field, "")
            theme_score = profile.theme_alignment_score(text)
            theme_boost = theme_score * 20.0
            
            # Event priority boost (+0 to +15 points)
            event_type = doc.get(event_type_field, "")
            event_score = profile.event_priority_score(event_type)
            event_boost = event_score * 15.0
            
            # Calculate adjusted score
            adjusted_score = base_score + theme_boost + event_boost
            
            # Add scoring details to document
            doc_copy = doc.copy()
            doc_copy['adjusted_feed_rank'] = adjusted_score
            doc_copy['theme_boost'] = theme_boost
            doc_copy['event_boost'] = event_boost
            doc_copy['original_rank'] = base_score
            
            reranked.append(doc_copy)
        
        # Sort by adjusted score
        reranked.sort(key=lambda d: d['adjusted_feed_rank'], reverse=True)
        
        logger.info(f"Reranked {len(reranked)} documents for {profile.client_name}")
        return reranked


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    profiler = ClientProfiler()
    
    print("\n" + "="*70)
    print("CLIENT PROFILER - IPS Analysis")
    print("="*70)
    
    for client_guid, profile in profiler.profiles.items():
        print(f"\n{profile.client_name} ({profile.archetype})")
        print(f"  Min Trust: {profile.min_trust_level}")
        print(f"  Risk: {profile.risk_tolerance}")
        print(f"  Alert Threshold: {profile.alert_threshold}")
        print(f"  Prohibited Sectors: {', '.join(profile.prohibited_sectors) if profile.prohibited_sectors else 'None'}")
        print(f"  ESG Exclusions: {len(profile.esg_exclusions)}")
        print(f"  Positive Themes: {', '.join(profile.positive_themes[:3])}...")
        print(f"  Top News Priorities: {', '.join(profile.news_priority[:3])}...")
        
        # Test theme scoring
        test_text = "breakthrough AI technology revolutionizes healthcare diagnostics"
        theme_score = profile.theme_alignment_score(test_text)
        print(f"  Theme score for AI/healthcare: {theme_score:.2f}")
    
    print("\n" + "="*70)
