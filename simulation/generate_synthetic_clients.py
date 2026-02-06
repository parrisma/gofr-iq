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
        ]

        watchlist = ["NXS", "FIN"]  # Monitoring other tech/fin

        return MockClient(
            guid="550e8400-e29b-41d4-a716-446655440001",  # Stable UUID for hedge fund client
            name="Quantum Momentum Partners",
            archetype=archetype,
            portfolio=portfolio,
            watchlist=watchlist,
            mandate_text=(
                "Quantum Momentum Partners pursues a global macro strategy focused on rates, FX, and liquidity "
                "inflection points, with tactical tilts around policy shifts and macro dislocations. The mandate "
                "targets medium-term themes and favors liquid instruments across regions."
            ),
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
                "Nebula Retirement Fund follows a conservative global macro mandate aimed at preserving capital "
                "while capturing medium-term opportunities in rates, FX, and diversified macro themes. The fund "
                "prioritizes stability, liquidity, and risk-controlled positioning."
            ),
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
                "DiamondHands420 runs a high‑conviction global macro playbook with an aggressive bias to "
                "volatility and fast‑moving FX/commodity narratives. The mandate is medium‑term but tilts toward "
                "event‑driven macro catalysts and sentiment swings."
            ),
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
                "Green Horizon Capital follows a strict ESG and eco‑innovation mandate, prioritizing renewable "
                "energy, clean transport, and sustainability leaders. The fund avoids high‑carbon exposures and "
                "targets medium‑term themes tied to climate policy, green infrastructure, and transition finance."
            ),
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

        watchlist = ["VIT", "ECO"]

        return MockClient(
            guid="550e8400-e29b-41d4-a716-446655440005",  # Stable UUID for long-bias client
            name="Sunrise Long Opportunities",
            archetype=archetype,
            portfolio=portfolio,
            watchlist=watchlist,
            mandate_text=(
                "Sunrise Long Opportunities runs a long‑bias global macro strategy that emphasizes durable growth "
                "themes and positive policy tailwinds. The mandate favors medium‑to‑long term compounding in high‑quality "
                "names while avoiding crowded shorts and excessive leverage."
            ),
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
                "Ironclad Short Strategies is a short‑bias global macro fund targeting over‑levered balance sheets, "
                "macro fragility, and downside catalysts. The mandate prioritizes medium‑term dislocations, credit stress, "
                "and policy tightening regimes, with strict risk controls on crowded trades."
            ),
        )
