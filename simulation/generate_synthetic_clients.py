"""
Generate Synthetic Clients for Simulation

Creates realistic client profiles with portfolios and watchlists
based on the universe of companies, sectors, and archetypes.
"""

from typing import List
from simulation.universe.types import ClientArchetype, MockClient, MockPosition
from simulation.universe.builder import UniverseBuilder


class ClientGenerator:
    """Generates synthetic clients with realistic portfolios."""

    def __init__(self, universe_builder: UniverseBuilder):
        self.builder = universe_builder
        self.tickers = universe_builder.get_tickers()

        # Define client archetypes
        self.archetypes = {
            "HEDGE_FUND": ClientArchetype(
                name="Hedge Fund",
                risk_appetite="AGGRESSIVE",
                min_trust_level=7,
                focus_sectors=["TECHNOLOGY", "FINANCIAL", "HEALTHCARE"],
                investment_horizon="SHORT_TERM",
            ),
            "PENSION_FUND": ClientArchetype(
                name="Pension Fund",
                risk_appetite="CONSERVATIVE",
                min_trust_level=9,
                focus_sectors=["FINANCIAL", "CONSUMER", "INDUSTRIALS"],
                investment_horizon="LONG_TERM",
            ),
            "RETAIL_TRADER": ClientArchetype(
                name="Retail Trader",
                risk_appetite="AGGRESSIVE",
                min_trust_level=5,
                focus_sectors=["TECHNOLOGY", "AUTO", "CONSUMER"],
                investment_horizon="SHORT_TERM",
            ),
            "ESG_FUND": ClientArchetype(
                name="ESG Fund",
                risk_appetite="CONSERVATIVE",
                min_trust_level=9,
                focus_sectors=["CONSUMER", "INDUSTRIALS", "ENERGY"],
                investment_horizon="LONG_TERM",
            ),
            "LONG_BIAS_FUND": ClientArchetype(
                name="Long Bias Fund",
                risk_appetite="MODERATE",
                min_trust_level=8,
                focus_sectors=["TECHNOLOGY", "INDUSTRIALS", "CONSUMER"],
                investment_horizon="LONG_TERM",
            ),
            "SHORT_BIAS_FUND": ClientArchetype(
                name="Short Bias Fund",
                risk_appetite="AGGRESSIVE",
                min_trust_level=8,
                focus_sectors=["FINANCIAL", "ENERGY", "CONSUMER"],
                investment_horizon="SHORT_TERM",
            ),
        }

    def generate_clients(self) -> List[MockClient]:
        """Generate a set of synthetic clients with portfolios."""
        clients = []

        # Hedge Fund - focus on tech and high-growth
        hedge_fund = self._generate_hedge_fund()
        clients.append(hedge_fund)

        # Pension Fund - conservative, diversified
        pension_fund = self._generate_pension_fund()
        clients.append(pension_fund)

        # Retail Trader - aggressive, meme stocks
        retail_trader = self._generate_retail_trader()
        clients.append(retail_trader)

        # ESG Fund - strong sustainability bias
        esg_fund = self._generate_esg_fund()
        clients.append(esg_fund)

        # Long Bias Fund
        long_bias = self._generate_long_bias_fund()
        clients.append(long_bias)

        # Short Bias Fund
        short_bias = self._generate_short_bias_fund()
        clients.append(short_bias)

        # Phase4 coverage clients (deterministic)
        clients.append(self._generate_genomics_partners())
        clients.append(self._generate_macro_rates_fund())
        clients.append(self._generate_crypto_ventures())

        return clients

    def _generate_hedge_fund(self) -> MockClient:
        """Generate an aggressive hedge fund client."""
        archetype = self.archetypes["HEDGE_FUND"]

        # Focus on tech and financial stocks
        portfolio = [
            MockPosition("QNTM", 0.15, "LONG"),  # AI chip maker
            MockPosition("BANKO", 0.12, "LONG"),  # Fintech bank
            MockPosition("VIT", 0.10, "LONG"),  # Luxury EV
            MockPosition("GTX", 0.08, "LONG"),  # Cloud/gaming
            MockPosition("NXS", 0.005, "LONG"),  # Tail holding for stress testing
        ]

        watchlist = ["NXS", "FIN"]  # Monitoring other tech/fin

        return MockClient(
            guid="550e8400-e29b-41d4-a716-446655440001",  # Stable UUID for hedge fund client
            name="Quantum Momentum Partners",
            archetype=archetype,
            portfolio=portfolio,
            watchlist=watchlist,
            mandate_text=(
                "Quantum Momentum Partners runs an aggressive technology-driven strategy focused on AI hardware, "
                "semiconductor supply chains, and next-generation compute platforms. The mandate targets short-to-medium "
                "term catalysts in chip design, GPU demand, and data-center buildout."
            ),
            mandate_themes=["ai", "semiconductor"],
        )

    def _generate_pension_fund(self) -> MockClient:
        """Generate a conservative pension fund client."""
        archetype = self.archetypes["PENSION_FUND"]

        # Diversified, blue-chip focus
        portfolio = [
            MockPosition("OMNI", 0.20, "LONG"),  # Conglomerate
            MockPosition("SHOPM", 0.15, "LONG"),  # E-commerce
            MockPosition("TRUCK", 0.12, "LONG"),  # Transportation
        ]

        watchlist = ["ECO", "STR"]  # Monitoring stable sectors

        return MockClient(
            guid="550e8400-e29b-41d4-a716-446655440002",  # Stable UUID for pension fund client
            name="Nebula Retirement Fund",
            archetype=archetype,
            portfolio=portfolio,
            watchlist=watchlist,
            mandate_text=(
                "Nebula Retirement Fund follows a conservative macro mandate focused on commodities, rates, and "
                "inflation-linked instruments. The fund prioritizes capital preservation through diversified real-asset "
                "exposure and duration management in a rising-rate environment."
            ),
            mandate_themes=["commodities", "rates", "consumer"],
        )

    def _generate_retail_trader(self) -> MockClient:
        """Generate an aggressive retail trader client."""
        archetype = self.archetypes["RETAIL_TRADER"]

        # High-risk, momentum plays
        portfolio = [
            MockPosition("VELO", 0.25, "LONG"),  # EV startup
            MockPosition("BLK", 0.20, "LONG"),  # Blockchain
        ]

        watchlist = ["QNTM", "LUXE"]  # Watching volatile tech

        return MockClient(
            guid="550e8400-e29b-41d4-a716-446655440003",  # Stable UUID for retail trader client
            name="DiamondHands420",
            archetype=archetype,
            portfolio=portfolio,
            watchlist=watchlist,
            mandate_text=(
                "DiamondHands420 runs a high-conviction strategy focused on blockchain protocols, EV battery "
                "technology, and momentum plays in disruptive sectors. The mandate favors short-term catalysts "
                "around token launches, battery breakthroughs, and retail sentiment swings."
            ),
            mandate_themes=["blockchain", "ev_battery"],
        )

    def _generate_esg_fund(self) -> MockClient:
        """Generate an ESG-focused fund client."""
        archetype = self.archetypes["ESG_FUND"]

        portfolio = [
            MockPosition("ECO", 0.18, "LONG"),  # Renewable energy
            MockPosition("STR", 0.14, "LONG"),  # Sustainable transport
            MockPosition("SHOPM", 0.10, "LONG"),  # Responsible retail
        ]

        watchlist = ["OMNI", "TRUCK"]

        # ESG fund has structured restrictions for filtering
        restrictions = {
            "ethical_sector": {
                "excluded_industries": ["TOBACCO", "WEAPONS", "GAMBLING", "FOSSIL_FUELS"],
                "exclusion_strictness": "hard",
            },
            "impact_sustainability": {
                "impact_themes": ["clean_energy", "sustainable_transport", "circular_economy"],
                "min_esg_score": 70,
                "require_sustainability_report": True,
            },
        }

        return MockClient(
            guid="550e8400-e29b-41d4-a716-446655440004",  # Stable UUID for ESG fund client
            name="Green Horizon Capital",
            archetype=archetype,
            portfolio=portfolio,
            watchlist=watchlist,
            mandate_text=(
                "Green Horizon Capital follows a strict ESG and energy-transition mandate, prioritizing renewable "
                "energy, clean transport, and sustainability leaders. The fund avoids high-carbon exposures and "
                "targets medium-term themes tied to climate policy, green infrastructure, and transition finance."
            ),
            mandate_themes=["esg", "energy_transition"],
            restrictions=restrictions,
        )

    def _generate_long_bias_fund(self) -> MockClient:
        """Generate a long-bias specialist client."""
        archetype = self.archetypes["LONG_BIAS_FUND"]

        portfolio = [
            MockPosition("QNTM", 0.22, "LONG"),
            MockPosition("SHOPM", 0.16, "LONG"),
            MockPosition("GTX", 0.12, "LONG"),
        ]

        watchlist = ["VIT", "ECO", "LUXE"]

        return MockClient(
            guid="550e8400-e29b-41d4-a716-446655440005",  # Stable UUID for long-bias client
            name="Sunrise Long Opportunities",
            archetype=archetype,
            portfolio=portfolio,
            watchlist=watchlist,
            mandate_text=(
                "Sunrise Long Opportunities runs a long-bias strategy focused on cloud infrastructure and consumer "
                "growth themes. The mandate favors medium-to-long term compounding in high-quality SaaS, e-commerce, "
                "and consumer-brand names with structural tailwinds."
            ),
            mandate_themes=["cloud", "consumer", "cybersecurity"],
        )

    def _generate_short_bias_fund(self) -> MockClient:
        """Generate a short-bias specialist client."""
        archetype = self.archetypes["SHORT_BIAS_FUND"]

        portfolio = [
            MockPosition("BANKO", 0.18, "SHORT"),
            MockPosition("OMNI", 0.14, "SHORT"),
            MockPosition("TRUCK", 0.10, "SHORT"),
        ]

        watchlist = ["FIN", "STR"]

        return MockClient(
            guid="550e8400-e29b-41d4-a716-446655440006",  # Stable UUID for short-bias client
            name="Ironclad Short Strategies",
            archetype=archetype,
            portfolio=portfolio,
            watchlist=watchlist,
            mandate_text=(
                "Ironclad Short Strategies is a short-bias fund targeting over-levered balance sheets, "
                "credit deterioration, and geopolitical downside catalysts. The mandate prioritizes medium-term "
                "dislocations in credit markets and policy tightening regimes, with strict risk controls."
            ),
            mandate_themes=["credit", "geopolitical"],
        )

    def _generate_genomics_partners(self) -> MockClient:
        """Generate a biotech/genomics client holding GENE (Phase4 coverage)."""
        archetype = self.archetypes["HEDGE_FUND"]

        portfolio = [
            MockPosition("GENE", 0.25, "LONG"),
            MockPosition("VIT", 0.08, "LONG"),
        ]

        watchlist = ["QNTM", "GTX"]

        return MockClient(
            guid="550e8400-e29b-41d4-a716-446655440007",
            name="Genomics Partners",
            archetype=archetype,
            portfolio=portfolio,
            watchlist=watchlist,
            mandate_text=(
                "Genomics Partners runs a biotech and genomics strategy focused on sequencing platforms, "
                "clinical catalysts, and compute-intensive biology. The mandate tracks AI-enabled drug discovery "
                "and infrastructure bottlenecks affecting genomics R&D throughput."
            ),
            mandate_themes=["genomics", "biotech", "ai"],
        )

    def _generate_macro_rates_fund(self) -> MockClient:
        """Generate a macro rates client holding PROP (Phase4 coverage)."""
        archetype = self.archetypes["PENSION_FUND"]

        portfolio = [
            MockPosition("PROP", 0.22, "LONG"),
            MockPosition("BANKO", 0.06, "LONG"),
        ]

        watchlist = ["OMNI", "TRUCK"]

        return MockClient(
            guid="550e8400-e29b-41d4-a716-446655440008",
            name="Macro Rates Fund",
            archetype=archetype,
            portfolio=portfolio,
            watchlist=watchlist,
            mandate_text=(
                "Macro Rates Fund runs a rates and real-assets strategy focused on inflation surprises, "
                "central bank policy, and duration-driven valuation shifts. The mandate emphasizes REIT sensitivity "
                "to yield curve moves and tightening cycles."
            ),
            mandate_themes=["rates", "inflation", "real_estate"],
        )

    def _generate_crypto_ventures(self) -> MockClient:
        """Generate a crypto/fintech client holding FIN (Phase4 coverage)."""
        archetype = self.archetypes["HEDGE_FUND"]

        portfolio = [
            MockPosition("FIN", 0.20, "LONG"),
            MockPosition("BLK", 0.12, "LONG"),
        ]

        watchlist = ["BANKO", "QNTM"]

        return MockClient(
            guid="550e8400-e29b-41d4-a716-446655440009",
            name="Crypto Ventures",
            archetype=archetype,
            portfolio=portfolio,
            watchlist=watchlist,
            mandate_text=(
                "Crypto Ventures runs a crypto and fintech strategy focused on protocol security, "
                "regulatory catalysts, and digital-asset market structure. The mandate targets DeFi risk events, "
                "exchange stability, and fintech disruption dynamics."
            ),
            mandate_themes=["blockchain", "fintech", "security"],
        )
