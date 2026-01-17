import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.services.graph_index import GraphIndex
from simulation.universe.builder import UniverseBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_universe():
    """
    Loads the synthetic universe (companies, relationships) into the Neo4j Graph.
    This acts as the "Hidden State" or "Ground Truth" for the simulation.
    """
    builder = UniverseBuilder()
    
    # We use the test configuration or current env. 
    # NOTE: This will write to whichever Neo4j is pointed to by env vars.
    logger.info("Connecting to Graph Database...")
    
    with GraphIndex() as graph:
        with graph.driver.session() as session:
            
            # 1. Clear existing Simulation Data (Optional: be careful in prod)
            logger.info("Injecting Companies...")
            
            for company in builder.get_tickers():
                # Create Company Node
                query = """
                MERGE (c:Company {guid: $guid})
                SET c.name = $name,
                    c.ticker = $ticker,
                    c.sector = $sector,
                    c.persona = $persona,
                    c.aliases = $aliases,
                    c.simulation_id = 'phase1'
                """
                params = {
                    "guid": f"company-{company.ticker}", # Deterministic GUID for sim
                    "name": company.name,
                    "ticker": company.ticker,
                    "sector": company.sector,
                    "persona": company.persona,
                    "aliases": company.aliases
                }
                session.run(query, params)
                
                # Create Instrument Node
                inst_query = """
                MERGE (i:Instrument {ticker: $ticker})
                SET i.guid = $inst_guid,
                    i.name = $name,
                    i.instrument_type = 'STOCK',
                    i.simulation_id = 'phase1'
                MERGE (c:Company {guid: $comp_guid})
                MERGE (i)-[:ISSUED_BY]->(c)
                """
                inst_params = {
                    "ticker": company.ticker,
                    "inst_guid": f"inst-{company.ticker}",
                    "name": company.name,
                    "comp_guid": params["guid"]
                }
                session.run(inst_query, inst_params)
                
            logger.info(f"Loaded {len(builder.get_tickers())} Companies and Instruments.")

            # 2. Inject Relationships
            logger.info("Injecting Graph Topology (Relationships)...")
            count = 0
            for rel in builder.get_relationships():
                # Cypher to link companies
                query = f"""
                MATCH (a:Company {{ticker: $src_ticker}})
                MATCH (b:Company {{ticker: $tgt_ticker}})
                MERGE (a)-[r:{rel.type}]->(b)
                SET r.description = $desc,
                    r.simulation_id = 'phase1'
                """
                params = {
                    "src_ticker": rel.source,
                    "tgt_ticker": rel.target,
                    "desc": rel.description
                }
                session.run(query, params)
                count += 1
                
            logger.info(f"Loaded {count} Relationships.")

if __name__ == "__main__":
    if not os.environ.get("NEO4J_URI"):
        logger.error("NEO4J_URI environment variable not set.")
        sys.exit(1)
        
    asyncio.run(load_universe())
