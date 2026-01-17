import random
from typing import List
from .types import MockTicker, MockRelationship

class UniverseBuilder:
    """
    Manages the creation and retrieval of the simulation universe entities.
    """
    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        self.tickers: List[MockTicker] = []
        self.relationships: List[MockRelationship] = []
        
        self._initialize_tickers()
        self._generate_aliases()
        self._generate_relationships()
    
    def _initialize_tickers(self):
        """Initializes the base list of MockTickers."""
        self.tickers = [
            # Mega-Caps
            MockTicker("GTX", "GigaTech Inc.", "Technology", "Mega-cap tech, dominant, antitrust target"),
            MockTicker("OMNI", "OmniCorp Global", "Conglomerate", "Industrial giant, slow steady growth"),
            MockTicker("QNTM", "Quantum Compute", "Technology", "High-growth AI/Hardware, extremely volatile"),
            
            # Mid-Caps & Growth
            MockTicker("NXS", "Nexus Software", "Technology", "SaaS, frequent M&A target"),
            MockTicker("VIT", "Vitality Pharma", "Healthcare", "Biotech, binary FDA outcomes"),
            MockTicker("ECO", "EcoPower Systems", "Energy", "Clean energy, regulatory sensitive"),
            MockTicker("BLK", "BlockChain Verify", "Financial", "Crypto proxy, sentiment driven"),
            
            # Industry Proxies
            MockTicker("STR", "Stratos Defense", "Industrials", "Defense contractor, government spending"),
            MockTicker("SHOPM", "ShopMart", "Consumer Cyclical", "Retail giant, consumer spending bellwether"),
            MockTicker("LUXE", "LuxeBrands", "Consumer Cyclical", "Luxury goods, China exposure"),
            MockTicker("BANKO", "BankOne", "Financial", "Major bank, interest rate sensitive"),
            MockTicker("FIN", "FinCorp", "Financial", "Fintech, regulatory risk"),
            MockTicker("VELO", "Velocity Motors", "Auto", "EV manufacturer, supply chain dependent"),
            MockTicker("TRUCK", "HeavyTrucks Inc.", "Auto", "Legacy auto, union labor issues"),
            MockTicker("GENE", "GeneSys", "Healthcare", "Genomics, R&D/Cash burn"),
            MockTicker("PROP", "PropCo REIT", "Real Estate", "Commercial real estate, interest rates"),
        ]

    def _generate_aliases(self):
        """Generates fuzzy aliases to simulate how news refers to companies without tickers."""
        for t in self.tickers:
            # Basic aliases
            t.aliases.append(t.name)
            t.aliases.append(t.ticker)
            
            # Sector-based aliases (e.g. "The <Sector> giant")
            if "Mega-cap" in t.persona or "giant" in t.persona:
                t.aliases.append(f"the {t.sector.lower()} giant")
                t.aliases.append("the market leader")
            
            # Name parts
            parts = t.name.split()
            if len(parts) > 1:
                t.aliases.append(parts[0]) # e.g. "GigaTech"
            
            # Contextual aliases based on persona logic
            if "Bank" in t.name:
                t.aliases.append("the lender")
            if "Pharma" in t.name or "Healthcare" in t.sector:
                t.aliases.append("the drugmaker")
            if "Auto" in t.sector:
                t.aliases.append("the automaker")

    def _generate_relationships(self):
        """Generates a graph of relationships (Supply chain, Competition, etc.)."""
        # 1. Intra-Sector Competition
        by_sector = {}
        for t in self.tickers:
            by_sector.setdefault(t.sector, []).append(t)
        
        for sector, companies in by_sector.items():
            if len(companies) > 1:
                # Create a ring of competition
                for i in range(len(companies)):
                    comp_a = companies[i]
                    comp_b = companies[(i + 1) % len(companies)]
                    self.relationships.append(MockRelationship(
                        source=comp_a.ticker,
                        target=comp_b.ticker,
                        type="COMPETES_WITH",
                        description=f"{comp_a.name} vs {comp_b.name} in {sector}"
                    ))

        # 2. Specific Supply Chain / Structural Relationships (Hardcoded for "Truth")
        specific_rels = [
            # Tech Supply Chain
            ("QNTM", "GTX", "SUPPLIED_BY", "Quantum chips used by GigaTech cloud"),
            ("NXS", "GTX", "PARTNER_OF", "Nexus software runs on GigaTechOS"),
            
            # Industrial Supply Chain
            ("VELO", "ECO", "PARTNER_OF", "Velocity Motors uses EcoPower batteries"),
            ("TRUCK", "STR", "SUPPLIES_TO", "HeavyTrucks defines logistics for Stratos Defense"),
            
            # Financial ecosystem
            ("BLK", "FIN", "COMPETES_WITH", "DeFi vs TradFi"),
            ("FIN", "BANKO", "DISRUPTS", "Fintech eroding bank margins"),
            
            # Conglomerate Interests
            ("OMNI", "VELO", "INVESTED_IN", "OmniCorp holds stake in EV maker"),
            ("OMNI", "VIT", "INTERESTED_IN", "Rumored acquisition target")
        ]
        
        for src, tgt, rel_type, desc in specific_rels:
            self.relationships.append(MockRelationship(src, tgt, rel_type, desc))

    def get_tickers(self) -> List[MockTicker]:
        """Returns the list of all companies in the universe."""
        return self.tickers

    def get_ticker(self, ticker_symbol: str) -> MockTicker:
        """Retrieves a specific ticker by symbol."""
        for t in self.tickers:
            if t.ticker == ticker_symbol:
                return t
        raise ValueError(f"Ticker {ticker_symbol} not found in universe")

    def get_relationships(self) -> List[MockRelationship]:
        """Returns the list of ground-truth relationships."""
        return self.relationships
