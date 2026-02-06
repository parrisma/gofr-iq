"""Client Restrictions Model for ESG & Compliance Filtering.

Defines structured constraints that affect story selection and portfolio compliance.

Categories:
- ethical_sector: Negative screening (excluded industries, faith-based rules)
- impact_sustainability: Positive screening (impact themes, stewardship)
- legal_regulatory: Jurisdictional constraints (future use)
- operational_risk: Portfolio limits (future use)
- tax_accounting: Structure/reporting (future use)

Usage:
    from app.models.restrictions import ClientRestrictions

    # Validate incoming dict
    restrictions = ClientRestrictions(**user_input)

    # Serialize for Neo4j storage
    json_str = restrictions.model_dump_json()

    # Deserialize from Neo4j
    restrictions = ClientRestrictions.model_validate_json(json_str)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EthicalSector(BaseModel):
    """Negative screening and values-based exclusions.

    Used for Anti-Pitch logic in story selection.
    """

    excluded_industries: list[str] = Field(
        default_factory=list,
        description=(
            "Industry codes to exclude from news feed. "
            "Examples: TOBACCO, WEAPONS, GAMBLING, ADULT_ENTERTAINMENT, FOSSIL_FUELS"
        ),
    )
    faith_based: Literal["none", "shariah", "catholic", "other"] = Field(
        default="none",
        description="Religious compliance framework affecting permissible investments",
    )


class ImpactSustainability(BaseModel):
    """Positive screening and active stewardship.

    Used for relevance boosting in story selection.
    """

    impact_mandate: bool = Field(
        default=False,
        description="Fund has specific positive impact goals (enables boost logic)",
    )
    impact_themes: list[str] = Field(
        default_factory=list,
        description=(
            "Themes for relevance boost in story ranking. "
            "Examples: clean_energy, sustainable_transport, circular_economy, social_housing, diversity"
        ),
    )
    stewardship_obligations: bool = Field(
        default=False,
        description="Fund requires active voting/engagement with portfolio companies",
    )


class LegalRegulatory(BaseModel):
    """Hard compliance rules from fund domicile (future use)."""

    jurisdictions: list[str] = Field(
        default_factory=list,
        description="ISO country codes for allowed/disallowed investment regions",
    )
    investor_eligibility: Literal["retail", "accredited", "institutional"] | None = Field(
        default=None,
        description="Investor qualification level for product distribution",
    )
    sanctions_restricted: bool = Field(
        default=False,
        description="Strict OFAC/sanctions compliance required",
    )


class OperationalRisk(BaseModel):
    """Quantitative portfolio construction limits (future use)."""

    max_issuer_concentration_pct: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Maximum percentage exposure to a single issuer",
    )
    leverage_limit_nav_pct: float | None = Field(
        default=None,
        ge=0.0,
        description="Maximum allowable leverage as percentage of NAV",
    )
    illiquid_asset_limit_nav_pct: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Cap on Level 3 or illiquid assets as percentage of NAV",
    )


class TaxAccounting(BaseModel):
    """Structure and reporting attributes (future use)."""

    structure: Literal["UCITS", "REIT", "mutual_fund", "hedge_fund", "other"] | None = Field(
        default=None,
        description="Fund legal structure",
    )
    reporting_standard: Literal["IFRS", "GAAP"] | None = Field(
        default=None,
        description="Accounting standard for valuation and P&L reporting",
    )
    tax_constraints: list[str] = Field(
        default_factory=list,
        description="Treaty limitations or withholding tax considerations",
    )


class ClientRestrictions(BaseModel):
    """Full restrictions schema for a client profile.

    Stored as JSON string on ClientProfile.restrictions property in Neo4j.

    Example:
        {
            "ethical_sector": {
                "excluded_industries": ["TOBACCO", "WEAPONS"],
                "faith_based": "none"
            },
            "impact_sustainability": {
                "impact_mandate": true,
                "impact_themes": ["clean_energy"],
                "stewardship_obligations": true
            }
        }
    """

    ethical_sector: EthicalSector = Field(default_factory=EthicalSector)
    impact_sustainability: ImpactSustainability = Field(default_factory=ImpactSustainability)
    legal_regulatory: LegalRegulatory = Field(default_factory=LegalRegulatory)
    operational_risk: OperationalRisk = Field(default_factory=OperationalRisk)
    tax_accounting: TaxAccounting = Field(default_factory=TaxAccounting)

    def has_exclusions(self) -> bool:
        """Check if any exclusion rules are defined."""
        return bool(self.ethical_sector.excluded_industries) or self.ethical_sector.faith_based != "none"

    def has_impact_mandate(self) -> bool:
        """Check if impact boosting should be applied."""
        return self.impact_sustainability.impact_mandate or bool(self.impact_sustainability.impact_themes)
