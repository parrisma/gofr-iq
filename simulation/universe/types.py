from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class MockTicker:
    """Represents a synthetic company in the simulation."""
    ticker: str
    name: str
    sector: str
    persona: str
    aliases: List[str] = field(default_factory=list)

@dataclass
class MockRelationship:
    """Represents a graph edge between two entities."""
    source: str  # Ticker of start node
    target: str  # Ticker of end node
    type: str    # Relationship type (e.g., SUPPLIER_OF, COMPETES_WITH)
    description: str = ""

@dataclass
class MockFactor:
    """Represents a macro economic factor in the simulation."""
    factor_id: str  # e.g., "INTEREST_RATES", "COMMODITY_PRICES"
    name: str  # Display name
    category: str  # e.g., "Monetary Policy", "Commodities", "Regulation"
    description: str = ""

@dataclass
class FactorExposure:
    """Represents an instrument's exposure to a macro factor."""
    ticker: str  # Instrument exposed
    factor_id: str  # Factor they're exposed to
    beta: float  # Sensitivity (-2.0 to +2.0, where 1.0 = market average)
    description: str = ""

@dataclass
class ClientArchetype:
    """Defines a type of investor for simulation."""
    name: str # e.g. "Hedge Fund", "Pension"
    risk_appetite: str # AGGRESSIVE, CONSERVATIVE
    min_trust_level: int # Lowest source trust score they find acceptable (1-10)
    focus_sectors: List[str] # List of sectors they care about
    investment_horizon: str # SHORT_TERM, LONG_TERM

@dataclass
class MockPosition:
    """A holding in a client portfolio."""
    ticker: str
    weight: float # Percentage 0.0-1.0
    sentiment: str # LONG, SHORT

@dataclass
class MockClient:
    """A generated client instance."""
    guid: str
    name: str
    archetype: ClientArchetype
    portfolio: List[MockPosition]
    watchlist: List[str]  # List of tickers
    mandate_text: Optional[str] = None
    mandate_themes: List[str] = field(default_factory=list)  # Controlled vocab from VALID_THEMES
    restrictions: Optional[Dict[str, Any]] = None  # ESG & compliance restrictions

