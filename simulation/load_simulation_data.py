import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.services.graph_index import GraphIndex
from simulation.universe.builder import UniverseBuilder
from simulation.generate_synthetic_clients import ClientGenerator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_simulation_data(load_universe: bool = True, load_clients: bool = True):
    """
    Load simulation data into Neo4j.

    Args:
        load_universe: When True, load groups, regions, sectors, companies, instruments, relationships, factors.
        load_clients: When True, load client archetypes, portfolios, and watchlists.

    Notes:
        - Clients depend on the universe being present. If `load_universe=False`, ensure the universe already exists.
        - Group creation always runs to guarantee downstream links.
    """
    logger.info("Initializing Universe Builder...")
    builder = UniverseBuilder()
    group = builder.get_default_group()

    logger.info("Connecting to Graph Database...")
    with GraphIndex() as graph:
        with graph.driver.session() as session:

            # --- PART 1: GROUP (always ensure) ---
            logger.info("Ensuring Default Group...")
            session.run(
                """
                MERGE (g:Group {guid: $guid})
                SET g.name = $name,
                    g.description = $description,
                    g.simulation_id = 'phase1'
                """,
                group,
            )

            # --- PART 2: UNIVERSE (optional) ---
            if load_universe:
                logger.info("Loading universe: regions, sectors, companies, instruments, relationships, factors...")

                # Regions
                for region in builder.get_regions():
                    session.run(
                        """
                        MERGE (r:Region {code: $code})
                        SET r.name = $name,
                            r.description = $description,
                            r.simulation_id = 'phase1'
                        """,
                        region,
                    )

                # Sectors
                for sector in builder.get_sectors():
                    session.run(
                        """
                        MERGE (s:Sector {code: $code})
                        SET s.name = $name,
                            s.description = $description,
                            s.simulation_id = 'phase1'
                        """,
                        sector,
                    )

                # Event Types
                for et in builder.get_event_types():
                    session.run(
                        """
                        MERGE (e:EventType {code: $code})
                        SET e.name = $name,
                            e.category = $category,
                            e.base_impact = $base_impact,
                            e.default_tier = $default_tier,
                            e.simulation_id = 'phase1'
                        """,
                        et,
                    )

                logger.info(f"Injecting {len(builder.get_tickers())} Companies & Instruments...")
                sector_map = {
                    "Technology": "TECHNOLOGY",
                    "Healthcare": "HEALTHCARE",
                    "Financial": "FINANCIAL",
                    "Consumer Cyclical": "CONSUMER",
                    "Industrials": "INDUSTRIALS",
                    "Energy": "ENERGY",
                    "Auto": "AUTO",
                    "Real Estate": "REAL_ESTATE",
                    "Conglomerate": "CONGLOMERATE",
                }
                default_region = "NORTH_AMERICA"

                for company in builder.get_tickers():
                    # Company
                    session.run(
                        """
                        MERGE (c:Company {guid: $guid})
                        SET c.name = $name,
                            c.ticker = $ticker,
                            c.sector = $sector,
                            c.persona = $persona,
                            c.aliases = $aliases,
                            c.simulation_id = 'phase1'
                        """,
                        {
                            "guid": f"company-{company.ticker}",
                            "name": company.name,
                            "ticker": company.ticker,
                            "sector": company.sector,
                            "persona": company.persona,
                            "aliases": company.aliases,
                        },
                    )

                    # Link to group, region, sector
                    session.run(
                        """
                        MATCH (c:Company {guid: $comp_guid})
                        MATCH (g:Group {guid: $group_guid})
                        MATCH (r:Region {code: $region_code})
                        MATCH (s:Sector {code: $sector_code})
                        MERGE (c)-[:IN_GROUP]->(g)
                        MERGE (c)-[:BELONGS_TO]->(r)
                        MERGE (c)-[:BELONGS_TO]->(s)
                        """,
                        {
                            "comp_guid": f"company-{company.ticker}",
                            "group_guid": group["guid"],
                            "region_code": default_region,
                            "sector_code": sector_map.get(company.sector, "CONGLOMERATE"),
                        },
                    )

                    # Instrument
                    session.run(
                        """
                        MERGE (i:Instrument {ticker: $ticker})
                        SET i.guid = $inst_guid,
                            i.name = $name,
                            i.instrument_type = 'STOCK',
                            i.simulation_id = 'phase1'
                        MERGE (c:Company {guid: $comp_guid})
                        MERGE (i)-[:ISSUED_BY]->(c)
                        """,
                        {
                            "ticker": company.ticker,
                            "inst_guid": f"inst-{company.ticker}",
                            "name": company.name,
                            "comp_guid": f"company-{company.ticker}",
                        },
                    )

                logger.info("Injecting Relationship Topology...")
                for rel in builder.get_relationships():
                    session.run(
                        f"""
                        MATCH (a:Company {{ticker: $src_ticker}})
                        MATCH (b:Company {{ticker: $tgt_ticker}})
                        MERGE (a)-[r:{rel.type}]->(b)
                        SET r.description = $desc,
                            r.simulation_id = 'phase1'
                        """,
                        {
                            "src_ticker": rel.source,
                            "tgt_ticker": rel.target,
                            "desc": rel.description,
                        },
                    )

                logger.info("Injecting Macro Factors & Exposures...")
                for factor in builder.get_factors():
                    session.run(
                        """
                        MERGE (f:Factor {factor_id: $factor_id})
                        SET f.name = $name,
                            f.category = $category,
                            f.description = $description,
                            f.simulation_id = 'phase1'
                        """,
                        {
                            "factor_id": factor.factor_id,
                            "name": factor.name,
                            "category": factor.category,
                            "description": factor.description,
                        },
                    )

                for exposure in builder.get_factor_exposures():
                    session.run(
                        """
                        MATCH (i:Instrument {ticker: $ticker})
                        MATCH (f:Factor {factor_id: $factor_id})
                        MERGE (i)-[e:EXPOSED_TO]->(f)
                        SET e.beta = $beta,
                            e.description = $description,
                            e.simulation_id = 'phase1'
                        """,
                        {
                            "ticker": exposure.ticker,
                            "factor_id": exposure.factor_id,
                            "beta": exposure.beta,
                            "description": exposure.description,
                        },
                    )

            # --- PART 3: CLIENTS (optional) ---
            if load_clients:
                logger.info("Generating synthetic clients...")
                gen = ClientGenerator(builder)
                clients = gen.generate_clients()
                logger.info(f"Injecting {len(clients)} Clients & Portfolios...")

                for client in clients:
                    # Client + profile
                    session.run(
                        """
                        MERGE (c:Client {guid: $guid})
                        SET c.name = $name,
                            c.simulation_id = 'phase2'

                        MERGE (ct:ClientType {code: $type_code})
                        MERGE (c)-[:IS_TYPE_OF]->(ct)

                        MERGE (cp:ClientProfile {guid: $profile_guid})
                        SET cp.risk_appetite = $risk,
                            cp.min_trust = $trust,
                            cp.horizon = $horizon
                        MERGE (c)-[:HAS_PROFILE]->(cp)

                        WITH c
                        MATCH (g:Group {guid: $group_guid})
                        MERGE (c)-[:IN_GROUP]->(g)
                        """,
                        {
                            "guid": client.guid,
                            "name": client.name,
                            "type_code": client.archetype.name.upper().replace(" ", "_"),
                            "profile_guid": f"profile-{client.guid}",
                            "risk": client.archetype.risk_appetite,
                            "trust": client.archetype.min_trust_level,
                            "horizon": client.archetype.investment_horizon,
                            "group_guid": group["guid"],
                        },
                    )

                    # Portfolio
                    session.run(
                        """
                        MATCH (c:Client {guid: $client_guid})
                        MERGE (p:Portfolio {guid: $port_guid})
                        MERGE (c)-[:HAS_PORTFOLIO]->(p)

                        WITH p
                        MATCH (g:Group {guid: $group_guid})
                        MERGE (p)-[:IN_GROUP]->(g)
                        """,
                        {
                            "client_guid": client.guid,
                            "port_guid": f"portfolio-{client.guid}",
                            "group_guid": group["guid"],
                        },
                    )

                    for pos in client.portfolio:
                        session.run(
                            """
                            MATCH (p:Portfolio {guid: $port_guid})
                            MATCH (i:Instrument {ticker: $ticker})
                            MERGE (p)-[h:HOLDS]->(i)
                            SET h.weight = $weight,
                                h.sentiment = $sentiment
                            """,
                            {
                                "port_guid": f"portfolio-{client.guid}",
                                "ticker": pos.ticker,
                                "weight": pos.weight,
                                "sentiment": pos.sentiment,
                            },
                        )

                    # Watchlist
                    session.run(
                        """
                        MATCH (c:Client {guid: $client_guid})
                        MERGE (w:Watchlist {guid: $wl_guid})
                        SET w.name = $wl_name
                        MERGE (c)-[:HAS_WATCHLIST]->(w)

                        WITH w
                        MATCH (g:Group {guid: $group_guid})
                        MERGE (w)-[:IN_GROUP]->(g)
                        """,
                        {
                            "client_guid": client.guid,
                            "wl_guid": f"watchlist-{client.guid}",
                            "wl_name": f"{client.name} Watchlist",
                            "group_guid": group["guid"],
                        },
                    )

                    for ticker in client.watchlist:
                        session.run(
                            """
                            MATCH (w:Watchlist {guid: $wl_guid})
                            MATCH (i:Instrument {ticker: $ticker})
                            MERGE (w)-[:WATCHES]->(i)
                            """,
                            {
                                "wl_guid": f"watchlist-{client.guid}",
                                "ticker": ticker,
                            },
                        )

    logger.info("Simulation Data Load Complete.")

if __name__ == "__main__":
    load_simulation_data()
