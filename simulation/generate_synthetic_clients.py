import json
import logging
from typing import List, Dict
from dataclasses import asdict

from simulation.universe.types import MockClient, ClientArchetype, MockPosition, MockTicker
from simulation.universe.builder import UniverseBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ClientGenerator:
    """Generates synthetic clients and their portfolios based on the Universe."""
    
    def __init__(self, universe: UniverseBuilder):
        self.universe = universe
        self.clients: List[MockClient] = []
        
        # Define Archetypes
        self.archetypes = {
            "HEDGE_FUND": ClientArchetype(
                name="Alpha Predator Fund",
                risk_appetite="AGGRESSIVE",
                min_trust_level=2,
                focus_sectors=["Technology", "Financial", "Healthcare"],
                investment_horizon="SHORT_TERM"
            ),
            "PENSION_FUND": ClientArchetype(
                name="SafeHarbor Pension",
                risk_appetite="CONSERVATIVE",
                min_trust_level=8,
                focus_sectors=["Conglomerate", "Consumer Cyclical", "Industrials"],
                investment_horizon="LONG_TERM"
            ),
            "RETAIL_TRADER": ClientArchetype(
                name="WSB Degen",
                risk_appetite="AGGRESSIVE",
                min_trust_level=1,
                focus_sectors=["Technology", "Auto", "Financial"],
                investment_horizon="SHORT_TERM"
            )
        }

    def generate_clients(self) -> List[MockClient]:
        """Generates the standard set of 3 simulation clients."""
        
        # 1. Hedge Fund (Long/Short Tech & Volatility)
        # Holds QNTM (Volatile), Shorts BANKO (Interest rates), Long VIT (Binary outcome)
        hf_portfolio = [
            MockPosition("QNTM", 0.40, "LONG"),
            MockPosition("BANKO", 0.20, "SHORT"),
            MockPosition("VIT", 0.30, "LONG"),
            MockPosition("GTX", 0.10, "LONG") # Benchmark weight
        ]
        self.clients.append(MockClient(
            guid="client-hedge-fund",
            name="Apex Capital",
            archetype=self.archetypes["HEDGE_FUND"],
            portfolio=hf_portfolio,
            watchlist=["BLK", "GENE"] # Watching crypto/genomics
        ))

        # 2. Pension Fund (Index heavy, low vol)
        # Holds OMNI, SHOPM, TRUCK
        pf_portfolio = [
            MockPosition("OMNI", 0.50, "LONG"),
            MockPosition("SHOPM", 0.30, "LONG"),
            MockPosition("TRUCK", 0.20, "LONG")
        ]
        self.clients.append(MockClient(
            guid="client-pension-fund",
            name="Teachers Retirement System",
            archetype=self.archetypes["PENSION_FUND"],
            portfolio=pf_portfolio,
            watchlist=["ECO", "PROP"] # Watching for stability
        ))
        
        # 3. Retail Trader (Chasing momentum)
        # Holds VELO (EVs), BLK (Crypto)
        rt_portfolio = [
            MockPosition("VELO", 0.70, "LONG"),
            MockPosition("BLK", 0.30, "LONG")
        ]
        self.clients.append(MockClient(
            guid="client-retail",
            name="DiamondHands420",
            archetype=self.archetypes["RETAIL_TRADER"],
            portfolio=rt_portfolio,
            watchlist=["GTX", "NXS"] # Watching popular tech
        ))
        
        return self.clients

    def export_clients_to_json(self, output_file: str):
        """Exports generated clients to a JSON file."""
        data = [asdict(c) for c in self.clients]
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Exported {len(self.clients)} clients to {output_file}")

if __name__ == "__main__":
    # Test generation
    u = UniverseBuilder()
    gen = ClientGenerator(u)
    clients = gen.generate_clients()
    for c in clients:
        print(f"Generated: {c.name} ({c.archetype.name}) with {len(c.portfolio)} positions")
