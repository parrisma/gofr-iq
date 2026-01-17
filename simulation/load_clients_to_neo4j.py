import os
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.services.graph_index import GraphIndex
from simulation.universe.builder import UniverseBuilder
from simulation.generate_synthetic_clients import ClientGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_clients():
    """
    Loads synthetic clients, their portfolios, and watchlists into Neo4j.
    """
    universe = UniverseBuilder()
    gen = ClientGenerator(universe)
    clients = gen.generate_clients()
    
    logger.info("Connecting to Graph Database...")
    
    with GraphIndex() as graph:
        with graph.driver.session() as session:
            logger.info(f"Injecting {len(clients)} Clients...")
            
            for client in clients:
                # 1. Create Client Node
                client_query = """
                MERGE (c:Client {guid: $guid})
                SET c.name = $name,
                    c.simulation_id = 'phase2'
                
                // Create Hierarchy
                MERGE (ct:ClientType {code: $type_code})
                MERGE (c)-[:IS_TYPE_OF]->(ct)
                
                // Create Profile
                MERGE (cp:ClientProfile {guid: $profile_guid})
                SET cp.risk_appetite = $risk,
                    cp.min_trust = $trust,
                    cp.horizon = $horizon
                MERGE (c)-[:HAS_PROFILE]->(cp)
                """
                client_params = {
                    "guid": client.guid,
                    "name": client.name,
                    "type_code": client.archetype.name.upper().replace(" ", "_"),
                    "profile_guid": f"profile-{client.guid}",
                    "risk": client.archetype.risk_appetite,
                    "trust": client.archetype.min_trust_level,
                    "horizon": client.archetype.investment_horizon
                }
                session.run(client_query, client_params)
                
                # 2. Create Portfolio & Positions
                port_query = """
                MATCH (c:Client {guid: $client_guid})
                MERGE (p:Portfolio {guid: $port_guid})
                MERGE (c)-[:HAS_PORTFOLIO]->(p)
                """
                port_params = {
                    "client_guid": client.guid,
                    "port_guid": f"portfolio-{client.guid}"
                }
                session.run(port_query, port_params)
                
                for pos in client.portfolio:
                    pos_query = """
                    MATCH (p:Portfolio {guid: $port_guid})
                    MATCH (i:Instrument {ticker: $ticker})
                    MERGE (p)-[h:HOLDS]->(i)
                    SET h.weight = $weight,
                        h.sentiment = $sentiment
                    """
                    pos_params = {
                        "port_guid": port_params["port_guid"],
                        "ticker": pos.ticker,
                        "weight": pos.weight,
                        "sentiment": pos.sentiment
                    }
                    session.run(pos_query, pos_params)
                    
                # 3. Create Watchlist
                wl_query = """
                MATCH (c:Client {guid: $client_guid})
                MERGE (w:Watchlist {guid: $wl_guid})
                SET w.name = $wl_name
                MERGE (c)-[:HAS_WATCHLIST]->(w)
                """
                wl_params = {
                    "client_guid": client.guid,
                    "wl_guid": f"watchlist-{client.guid}",
                    "wl_name": f"{client.name} Watchlist"
                }
                session.run(wl_query, wl_params)
                
                for ticker in client.watchlist:
                    watch_query = """
                    MATCH (w:Watchlist {guid: $wl_guid})
                    MATCH (i:Instrument {ticker: $ticker})
                    MERGE (w)-[:WATCHES]->(i)
                    """
                    watch_params = {
                        "wl_guid": wl_params["wl_guid"],
                        "ticker": ticker
                    }
                    session.run(watch_query, watch_params)

        logger.info("Client injection complete.")

if __name__ == "__main__":
    if not os.environ.get("NEO4J_URI"):
        logger.error("NEO4J_URI environment variable not set.")
        sys.exit(1)
    
    load_clients()
