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
        )
