import sys
import logging
import json
import random
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.services.graph_index import GraphIndex
from app.services.llm_service import ChatMessage, create_llm_service, llm_available, LLMService
from simulation.universe.builder import UniverseBuilder
from simulation.generate_synthetic_clients import ClientGenerator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

_mandate_llm_service: LLMService | None = None


def _random_impact_threshold(client_name: str) -> float:
    """Generate a deterministic 'random' impact threshold in 10-pt increments.

    Range: 20..50 (inclusive), rounded to 10.
    Kept moderate so small simulations still generate non-empty avatar feeds.
    """
    rng = random.Random(client_name)
    return float(rng.choice(list(range(20, 51, 10))))


def _build_mandate_text(client_name: str) -> str:
    """Generate a mandate text based on the client name."""
    fallback = (
        f"{client_name} runs a global macro strategy focused on rates, FX, and commodities. "
        "The mandate emphasizes medium-term positioning, policy divergence, and macro dislocations. "
        "Risk is diversified across geographies and asset classes with strict drawdown limits and "
        "liquidity constraints."
    )

    if not llm_available():
        return fallback

    global _mandate_llm_service
    if _mandate_llm_service is None:
        _mandate_llm_service = create_llm_service()

    try:
        prompt = (
            "Write a short investment mandate (2-3 sentences) for a client. "
            "Use the client name to add a realistic flavor. "
            "Focus on global macro, medium-term horizon, and mention rates/FX/commodities. "
            "Keep it concise and suitable for semantic matching."
        )
        result = _mandate_llm_service.chat_completion(
            messages=[
                ChatMessage(role="system", content="You write concise investment mandates."),
                ChatMessage(role="user", content=f"Client name: {client_name}"),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=0.4,
            max_tokens=120,
        )
        content = result.content.strip()
        return content or fallback
    except Exception as exc:
        logger.warning(f"Mandate LLM generation failed, using fallback: {exc}")
        return fallback


def _get_admin_token() -> str:
    """Get admin token from bootstrap tokens file."""
    token_file = Path(__file__).parent.parent / "secrets" / "bootstrap_tokens.json"
    if not token_file.exists():
        raise FileNotFoundError(
            f"Bootstrap tokens file not found: {token_file}\n"
            "Run ./scripts/start-prod.sh to generate tokens."
        )
    with open(token_file, "r") as f:
        tokens = json.load(f)
    return tokens["admin_token"]


def _get_simulation_token() -> str:
    """Get group-simulation token from simulation tokens file.
    
    Clients should be created with group-simulation token so they're assigned
    to the group-simulation group (not admin group).
    """
    token_file = Path(__file__).parent / "tokens.json"
    if not token_file.exists():
        raise FileNotFoundError(
            f"Simulation tokens file not found: {token_file}\n"
            "Run ./simulation/run_simulation.sh to generate tokens."
        )
    with open(token_file, "r") as f:
        tokens = json.load(f)
    
    if "group-simulation" not in tokens:
        raise KeyError(
            "group-simulation token not found in simulation/tokens.json\n"
            "Run ./simulation/run_simulation.sh to regenerate tokens."
        )
    
    return tokens["group-simulation"]


def _create_client_via_mcp(client_data: dict[str, Any], token: str) -> dict[str, Any]:
    """Create client via MCP tools using manage_client script.
    
    Args:
        client_data: Client creation parameters
        token: Admin JWT token
        
    Returns:
        Response from create_client MCP call
    """
    import subprocess
    import tempfile
    
    project_root = Path(__file__).parent.parent
    cmd = [
        str(project_root / "scripts" / "manage_client.sh"),
        "--docker", "--token", token,
        "create",
        "--name", client_data["name"],
        "--type", client_data["client_type"],
    ]
    
    # Add optional parameters
    if "alert_frequency" in client_data:
        cmd.extend(["--alert-frequency", client_data["alert_frequency"]])
    if "impact_threshold" in client_data:
        cmd.extend(["--impact-threshold", str(client_data["impact_threshold"])])
    if "mandate_type" in client_data:
        cmd.extend(["--mandate-type", client_data["mandate_type"]])
    if "mandate_text" in client_data:
        cmd.extend(["--mandate-text", client_data["mandate_text"]])
    if "benchmark" in client_data:
        cmd.extend(["--benchmark", client_data["benchmark"]])
    if "horizon" in client_data:
        cmd.extend(["--horizon", client_data["horizon"]])
    if client_data.get("esg_constrained", False):
        cmd.append("--esg-constrained")
    
    # Handle restrictions via temp file if present
    restrictions_file = None
    if "restrictions" in client_data and client_data["restrictions"]:
        restrictions_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump(client_data["restrictions"], restrictions_file)
        restrictions_file.close()
        cmd.extend(["--restrictions-file", restrictions_file.name])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_root)
    finally:
        # Clean up temp file
        if restrictions_file:
            Path(restrictions_file.name).unlink(missing_ok=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create client via MCP: {result.stderr}")
    
    response = json.loads(result.stdout)
    if response.get("status") == "error":
        raise RuntimeError(f"MCP error: {response.get('message', 'Unknown error')}")
    
    return response


def _add_holdings_via_mcp(client_guid: str, holdings: list[tuple[str, float]], token: str) -> None:
    """Add holdings to client portfolio via MCP.
    
    Args:
        client_guid: Client UUID
        holdings: List of (ticker, weight) tuples
        token: Admin JWT token
    """
    import subprocess
    
    project_root = Path(__file__).parent.parent
    
    for ticker, weight in holdings:
        cmd = [
            str(project_root / "scripts" / "manage_client.sh"),
            "--docker", "--token", token,
            "add-holding",
            client_guid,
            "--ticker", ticker,
            "--weight", str(weight),
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_root)
        
        if result.returncode != 0:
            logger.warning(f"Failed to add holding {ticker} to {client_guid}: {result.stderr}")
            continue
        
        response = json.loads(result.stdout)
        if response.get("status") == "error":
            logger.warning(f"MCP error adding {ticker}: {response.get('message', 'Unknown')}")


def _add_watchlist_via_mcp(client_guid: str, tickers: list[str], token: str) -> None:
    """Add watchlist items to client via MCP.
    
    Args:
        client_guid: Client UUID
        tickers: List of tickers to watch
        token: Admin JWT token
    """
    import subprocess
    
    project_root = Path(__file__).parent.parent
    
    for ticker in tickers:
        cmd = [
            str(project_root / "scripts" / "manage_client.sh"),
            "--docker", "--token", token,
            "add-watch",
            client_guid,
            "--ticker", ticker,
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_root)
        
        if result.returncode != 0:
            logger.warning(f"Failed to add watch {ticker} to {client_guid}: {result.stderr}")
            continue
        
        response = json.loads(result.stdout)
        if response.get("status") == "error":
            logger.warning(f"MCP error adding watch {ticker}: {response.get('message', 'Unknown')}")


def _get_existing_simulation_clients(token: str) -> dict[str, str]:
    """Get existing simulation clients by name.
    
    Returns:
        Dict mapping client name to client_guid
    """
    import subprocess
    
    project_root = Path(__file__).parent.parent
    cmd = [
        str(project_root / "scripts" / "manage_client.sh"),
        "--docker", "--token", token,
        "list",
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_root)
    
    if result.returncode != 0:
        logger.warning(f"Failed to list clients: {result.stderr}")
        return {}
    
    try:
        response = json.loads(result.stdout)
        if response.get("status") != "success":
            return {}
        
        clients = response.get("data", {}).get("clients", [])
        # Map client names to GUIDs
        return {c["name"]: c["client_guid"] for c in clients}
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to parse client list: {e}")
        return {}

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
                        """,  # type: ignore[arg-type] - f-string query with dynamic rel.type
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
                
                # Get simulation token for client creation (assigns to group-simulation)
                # Use admin token only as fallback
                try:
                    token = _get_simulation_token()
                except (FileNotFoundError, KeyError) as e:
                    logger.warning(f"Simulation token not available: {e}")
                    logger.warning("Falling back to admin token - clients will be in admin group")
                    try:
                        token = _get_admin_token()
                    except FileNotFoundError as e:
                        logger.error(str(e))
                        return
                
                # Check for existing simulation clients to avoid duplicates
                logger.info("Checking for existing simulation clients...")
                existing_clients = _get_existing_simulation_clients(token)
                logger.info(f"Found {len(existing_clients)} existing clients in database")
                
                logger.info(f"Creating/updating {len(clients)} Clients via MCP...")
                
                for client in clients:
                    # Check if client already exists by name
                    if client.name in existing_clients:
                        existing_guid = existing_clients[client.name]
                        logger.info(f"Client '{client.name}' already exists ({existing_guid}), skipping creation...")
                        
                        # Optionally update holdings/watchlist for existing client
                        # For now, we skip to avoid duplicates
                        continue
                    
                    logger.info(f"Creating client: {client.name}")
                    
                    # Map archetype to client type
                    type_map = {
                        "Hedge Fund": "HEDGE_FUND",
                        "Pension Fund": "PENSION_FUND",
                        "Retail Trader": "RETAIL_TRADER",
                    }
                    client_type = type_map.get(client.archetype.name, "HEDGE_FUND")
                    
                    # Map investment horizon
                    horizon = "medium"

                    impact_threshold = _random_impact_threshold(client.name)
                    mandate_text = client.mandate_text or _build_mandate_text(client.name)
                    
                    # Determine if client is ESG constrained (has exclusions)
                    esg_constrained = False
                    if client.restrictions:
                        ethical = client.restrictions.get("ethical_sector", {})
                        if ethical.get("excluded_industries"):
                            esg_constrained = True
                    
                    # Create client via MCP (creates Client, Profile, Portfolio, Watchlist)
                    try:
                        response = _create_client_via_mcp(
                            {
                                "name": client.name,
                                "client_type": client_type,
                                "alert_frequency": "weekly",
                                "impact_threshold": impact_threshold,
                                "mandate_type": "global_macro",
                                "mandate_text": mandate_text,
                                "horizon": horizon,
                                "esg_constrained": esg_constrained,
                                "restrictions": client.restrictions,
                            },
                            token,
                        )
                        
                        created_guid = response["data"]["client_guid"]
                        logger.info(f"  Created {client.name}: {created_guid}")
                        
                        # Add holdings
                        if client.portfolio:
                            holdings = [(pos.ticker, pos.weight) for pos in client.portfolio]
                            logger.info(f"  Adding {len(holdings)} holdings...")
                            _add_holdings_via_mcp(created_guid, holdings, token)
                        
                        # Add watchlist
                        if client.watchlist:
                            logger.info(f"  Adding {len(client.watchlist)} watchlist items...")
                            _add_watchlist_via_mcp(created_guid, client.watchlist, token)
                        
                    except RuntimeError as e:
                        logger.error(f"  Failed to create client {client.name}: {e}")
                        continue

    logger.info("Simulation Data Load Complete.")

if __name__ == "__main__":
    load_simulation_data()
