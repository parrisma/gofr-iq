import random
from typing import List
from .types import MockTicker, MockRelationship, MockFactor, FactorExposure

# --- Taxonomy Definitions ---

# Default Group for simulation universe
DEFAULT_GROUP = {
    "guid": "group-simulation",
    "name": "simulation-group",
    "description": "Default group for simulation universe entities"
}

# Event Types Taxonomy
EVENT_TYPES = [
    {"code": "EARNINGS", "name": "Earnings Report", "category": "Financial", "base_impact": 0.7, "default_tier": 2},
    {"code": "M&A", "name": "Merger & Acquisition", "category": "Corporate", "base_impact": 0.9, "default_tier": 1},
    {"code": "REGULATORY", "name": "Regulatory Action", "category": "Regulatory", "base_impact": 0.8, "default_tier": 1},
    {"code": "PRODUCT_LAUNCH", "name": "Product Launch", "category": "Innovation", "base_impact": 0.6, "default_tier": 2},
    {"code": "EXEC_CHANGE", "name": "Executive Change", "category": "Corporate", "base_impact": 0.5, "default_tier": 3},
    {"code": "LITIGATION", "name": "Legal Action", "category": "Legal", "base_impact": 0.7, "default_tier": 2},
    {"code": "FDA_APPROVAL", "name": "FDA Approval/Denial", "category": "Regulatory", "base_impact": 0.95, "default_tier": 1},
    {"code": "MACRO_ECON", "name": "Macroeconomic Event", "category": "Economic", "base_impact": 0.8, "default_tier": 1},
    {"code": "SUPPLY_CHAIN", "name": "Supply Chain Issue", "category": "Operations", "base_impact": 0.6, "default_tier": 2},
    {"code": "CYBER_SECURITY", "name": "Cyber Security Incident", "category": "Technology", "base_impact": 0.75, "default_tier": 2},
]

# Regions Taxonomy
REGIONS = [
    {"code": "NORTH_AMERICA", "name": "North America", "description": "US, Canada, Mexico"},
    {"code": "EUROPE", "name": "Europe", "description": "European Union and UK"},
    {"code": "ASIA_PACIFIC", "name": "Asia Pacific", "description": "China, Japan, India, SE Asia"},
    {"code": "LATIN_AMERICA", "name": "Latin America", "description": "Central and South America"},
    {"code": "MIDDLE_EAST", "name": "Middle East", "description": "Middle Eastern countries"},
    {"code": "AFRICA", "name": "Africa", "description": "African continent"},
]

# Sectors Taxonomy (aligned with company sectors)
SECTORS = [
    {"code": "TECHNOLOGY", "name": "Technology", "description": "Software, Hardware, IT Services"},
    {"code": "HEALTHCARE", "name": "Healthcare", "description": "Pharma, Biotech, Medical Devices"},
    {"code": "FINANCIAL", "name": "Financial Services", "description": "Banks, Fintech, Insurance"},
    {"code": "CONSUMER", "name": "Consumer", "description": "Retail, Luxury, Consumer Goods"},
    {"code": "INDUSTRIALS", "name": "Industrials", "description": "Manufacturing, Defense, Construction"},
    {"code": "ENERGY", "name": "Energy", "description": "Oil, Gas, Renewables"},
    {"code": "AUTO", "name": "Automotive", "description": "Auto manufacturers, EV, Suppliers"},
    {"code": "REAL_ESTATE", "name": "Real Estate", "description": "REITs, Property Development"},
    {"code": "CONGLOMERATE", "name": "Conglomerate", "description": "Diversified holdings"},
]

class UniverseBuilder:
    """
    Manages the creation and retrieval of the simulation universe entities.
    """
    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        self.tickers: List[MockTicker] = []
        self.relationships: List[MockRelationship] = []
        self.factors: List[MockFactor] = []
        self.factor_exposures: List[FactorExposure] = []
        
        self._initialize_tickers()
        self._generate_aliases()
        self._initialize_factors()
        self._generate_relationships()
        self._generate_factor_exposures()
    
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

    def _initialize_factors(self):
        """Initialize macro economic factors that affect instruments."""
        self.factors = [
            MockFactor(
                factor_id="INTEREST_RATES",
                name="Interest Rate Changes",
                category="Monetary Policy",
                description="Central bank interest rate policy changes"
            ),
            MockFactor(
                factor_id="COMMODITY_PRICES",
                name="Commodity Price Volatility",
                category="Commodities",
                description="Oil, metals, agricultural commodity price movements"
            ),
            MockFactor(
                factor_id="REGULATION",
                name="Regulatory Environment",
                category="Policy",
                description="Government regulatory changes and enforcement"
            ),
            MockFactor(
                factor_id="CONSUMER_SPENDING",
                name="Consumer Spending",
                category="Economic",
                description="Household consumption and retail sales trends"
            ),
            MockFactor(
                factor_id="CHINA_ECONOMY",
                name="China Economic Growth",
                category="Geographic",
                description="Chinese GDP growth and economic policy"
            ),
        ]

    def _generate_factor_exposures(self):
        """Generate factor exposures (EXPOSED_TO relationships) for instruments."""
        # Interest rate sensitivity
        rate_sensitive = [
            ("BANKO", 1.8, "Banks benefit from rising rates (higher net interest margin)"),
            ("PROP", -1.5, "REITs hurt by rising rates (discount future cash flows)"),
            ("FIN", 1.2, "Fintech lending margins expand with rates"),
            ("LUXE", -0.8, "Luxury purchases often financed, hurt by rate hikes"),
        ]
        for ticker, beta, desc in rate_sensitive:
            self.factor_exposures.append(
                FactorExposure(ticker, "INTEREST_RATES", beta, desc)
            )

        # Commodity price exposure
        commodity_exposed = [
            ("ECO", -1.3, "Clean energy input costs rise with commodity prices"),
            ("VELO", -1.1, "EV battery materials (lithium) tied to commodities"),
            ("TRUCK", -0.9, "Fuel and steel costs squeeze margins"),
            ("STR", 0.6, "Defense contracts have cost-plus pricing"),
        ]
        for ticker, beta, desc in commodity_exposed:
            self.factor_exposures.append(
                FactorExposure(ticker, "COMMODITY_PRICES", beta, desc)
            )

        # Regulatory exposure
        regulatory_risk = [
            ("GTX", -1.4, "Antitrust scrutiny, platform regulation"),
            ("BLK", -1.6, "Crypto regulation existential risk"),
            ("FIN", -1.2, "Fintech licensing and compliance costs"),
            ("VIT", 1.5, "FDA approval binary events"),
            ("GENE", 1.3, "Genomics regulatory approval upside"),
            ("ECO", 1.0, "Clean energy subsidies and mandates"),
        ]
        for ticker, beta, desc in regulatory_risk:
            self.factor_exposures.append(
                FactorExposure(ticker, "REGULATION", beta, desc)
            )

        # Consumer spending exposure
        consumer_exposed = [
            ("SHOPM", 1.5, "Retail giant directly tied to consumer spending"),
            ("LUXE", 1.8, "Luxury goods highly elastic to disposable income"),
            ("VELO", 1.2, "Premium EV purchases discretionary"),
            ("TRUCK", 0.9, "Commercial fleet purchases tied to business spending"),
        ]
        for ticker, beta, desc in consumer_exposed:
            self.factor_exposures.append(
                FactorExposure(ticker, "CONSUMER_SPENDING", beta, desc)
            )

        # China exposure
        china_exposed = [
            ("LUXE", 2.0, "40% revenue from China luxury buyers"),
            ("QNTM", 1.3, "AI chip supply chain and China manufacturing"),
            ("OMNI", 1.1, "Conglomerate with significant China operations"),
            ("GTX", 0.8, "Cloud services and China market access"),
        ]
        for ticker, beta, desc in china_exposed:
            self.factor_exposures.append(
                FactorExposure(ticker, "CHINA_ECONOMY", beta, desc)
            )

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

    def get_factors(self) -> List[MockFactor]:
        """Returns the list of macro economic factors."""
        return self.factors

    def get_factor_exposures(self) -> List[FactorExposure]:
        """Returns the list of factor exposure relationships."""
        return self.factor_exposures

    def get_event_types(self) -> List[dict]:
        """Returns the list of event type definitions."""
        return EVENT_TYPES

    def get_regions(self) -> List[dict]:
        """Returns the list of region definitions."""
        return REGIONS

    def get_sectors(self) -> List[dict]:
        """Returns the list of sector definitions."""
        return SECTORS

    def get_default_group(self) -> dict:
        """Returns the default simulation group."""
        return DEFAULT_GROUP
