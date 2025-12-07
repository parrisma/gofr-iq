"""Test data store for managing test data directories and cleanup.

This module provides the DataStore class that creates and manages
the test data environment for gofr-iq tests. It follows the canonical
document store structure defined in IMPLEMENTATION.md.

Directory Structure:
    test/data/
    ├── documents/
    │   └── {group_guid}/
    │       └── {YYYY-MM-DD}/
    │           └── {guid}.json
    ├── sources/
    │   └── {group_guid}/
    │       └── {source_guid}.json
    ├── groups/
    │   └── {group_guid}.json
    └── chroma/
        └── ...
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4


class DataStore:
    """Manages test data directories for gofr-iq tests.
    
    Creates an isolated test data environment that mirrors the production
    canonical document store structure. Supports setup and teardown for
    clean test isolation.
    
    Attributes:
        base_path: Root path for test data (default: test/data)
        documents_path: Path to documents directory
        sources_path: Path to sources directory
        groups_path: Path to groups directory
        chroma_path: Path to ChromaDB storage directory
    
    Example:
        >>> store = DataStore()
        >>> store.setup()
        >>> # Run tests...
        >>> store.teardown()
        
        # Or use as context manager:
        >>> with DataStore() as store:
        ...     # Run tests with store
    """
    
    # Subdirectory names (matching IMPLEMENTATION.md spec)
    DOCUMENTS_DIR = "documents"
    SOURCES_DIR = "sources"
    GROUPS_DIR = "groups"
    CHROMA_DIR = "chroma"
    LOGS_DIR = "logs"
    
    def __init__(self, base_path: Optional[Path] = None):
        """Initialize test data store.
        
        Args:
            base_path: Root path for test data. Defaults to test/data
                      relative to the project root.
        """
        if base_path is None:
            # Default to test/data relative to this file's location
            base_path = Path(__file__).parent.parent / "data"
        
        self.base_path = Path(base_path)
        self.documents_path = self.base_path / self.DOCUMENTS_DIR
        self.sources_path = self.base_path / self.SOURCES_DIR
        self.groups_path = self.base_path / self.GROUPS_DIR
        self.chroma_path = self.base_path / self.CHROMA_DIR
        self.logs_path = self.base_path / self.LOGS_DIR
        
        self._is_setup = False
    
    def setup(self) -> "DataStore":
        """Create all test data directories.
        
        Creates the complete directory structure for test data storage.
        Safe to call multiple times - will not fail if directories exist.
        
        Returns:
            Self for method chaining.
        
        Raises:
            OSError: If directory creation fails due to permissions or disk issues.
        """
        directories = [
            self.documents_path,
            self.sources_path,
            self.groups_path,
            self.chroma_path,
            self.logs_path,
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        
        self._is_setup = True
        return self
    
    def teardown(self, remove_all: bool = False) -> None:
        """Clean up test data.
        
        By default, preserves the directory structure but removes all files.
        Set remove_all=True to completely remove the test data directory.
        
        Args:
            remove_all: If True, removes the entire base_path directory.
                       If False (default), clears contents but keeps structure.
        """
        if remove_all and self.base_path.exists():
            shutil.rmtree(self.base_path)
        else:
            # Clear contents but preserve structure
            for subdir in [self.documents_path, self.sources_path, 
                          self.groups_path, self.chroma_path, self.logs_path]:
                if subdir.exists():
                    for item in subdir.iterdir():
                        if item.is_dir():
                            shutil.rmtree(item)
                        else:
                            item.unlink()
        
        self._is_setup = False
    
    def reset(self) -> "DataStore":
        """Clear all test data and recreate empty directories.
        
        Convenience method combining teardown and setup.
        
        Returns:
            Self for method chaining.
        """
        self.teardown(remove_all=False)
        return self.setup()
    
    @property
    def is_setup(self) -> bool:
        """Check if the test data store has been set up."""
        return self._is_setup and all(
            path.exists() for path in [
                self.documents_path,
                self.sources_path,
                self.groups_path,
                self.chroma_path,
            ]
        )
    
    def get_group_documents_path(self, group_guid: str) -> Path:
        """Get the documents directory path for a specific group.
        
        Args:
            group_guid: The group's GUID.
            
        Returns:
            Path to the group's documents directory.
        """
        return self.documents_path / group_guid
    
    def get_group_sources_path(self, group_guid: str) -> Path:
        """Get the sources directory path for a specific group.
        
        Args:
            group_guid: The group's GUID.
            
        Returns:
            Path to the group's sources directory.
        """
        return self.sources_path / group_guid
    
    def get_group_path(self, group_guid: str) -> Path:
        """Get the path to a group's metadata file.
        
        Args:
            group_guid: The group's GUID.
            
        Returns:
            Path to the group's JSON file.
        """
        return self.groups_path / f"{group_guid}.json"
    
    def get_document_path(self, group_guid: str, doc_guid: str, 
                          date: Optional[datetime] = None) -> Path:
        """Get the path for a document file.
        
        Args:
            group_guid: The group's GUID.
            doc_guid: The document's GUID.
            date: The document date (for directory organization).
                  Defaults to today.
        
        Returns:
            Path to the document's JSON file.
        """
        if date is None:
            date = datetime.now()
        date_str = date.strftime("%Y-%m-%d")
        return self.documents_path / group_guid / date_str / f"{doc_guid}.json"
    
    def get_source_path(self, group_guid: str, source_guid: str) -> Path:
        """Get the path for a source file.
        
        Args:
            group_guid: The group's GUID.
            source_guid: The source's GUID.
        
        Returns:
            Path to the source's JSON file.
        """
        return self.sources_path / group_guid / f"{source_guid}.json"
    
    def create_group_directory(self, group_guid: str) -> tuple[Path, Path]:
        """Create directories for a new group.
        
        Creates both the documents and sources directories for a group.
        
        Args:
            group_guid: The group's GUID.
        
        Returns:
            Tuple of (documents_path, sources_path) for the group.
        """
        docs_path = self.get_group_documents_path(group_guid)
        sources_path = self.get_group_sources_path(group_guid)
        
        docs_path.mkdir(parents=True, exist_ok=True)
        sources_path.mkdir(parents=True, exist_ok=True)
        
        return docs_path, sources_path
    
    def create_date_directory(self, group_guid: str, 
                              date: Optional[datetime] = None) -> Path:
        """Create a date-based directory for documents.
        
        Args:
            group_guid: The group's GUID.
            date: The date for the directory. Defaults to today.
        
        Returns:
            Path to the created date directory.
        """
        if date is None:
            date = datetime.now()
        date_str = date.strftime("%Y-%m-%d")
        date_path = self.documents_path / group_guid / date_str
        date_path.mkdir(parents=True, exist_ok=True)
        return date_path
    
    def write_json(self, path: Path, data: dict) -> Path:
        """Write JSON data to a file.
        
        Creates parent directories if they don't exist.
        
        Args:
            path: The file path to write to.
            data: The data to serialize as JSON.
        
        Returns:
            The path that was written to.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path
    
    def read_json(self, path: Path) -> dict:
        """Read JSON data from a file.
        
        Args:
            path: The file path to read from.
        
        Returns:
            The parsed JSON data.
        
        Raises:
            FileNotFoundError: If the file doesn't exist.
            json.JSONDecodeError: If the file contains invalid JSON.
        """
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    @staticmethod
    def generate_guid() -> str:
        """Generate a new random GUID.
        
        Returns:
            A new UUID4 string.
        """
        return str(uuid4())
    
    # =========================================================================
    # Sample Data Generation (Step 0.2)
    # =========================================================================
    
    def generate_sample_data(self) -> dict:
        """Generate sample test data: 2 groups, 3 tokens, 3 sources, 10 documents.
        
        Creates a complete test dataset following the canonical schema defined
        in IMPLEMENTATION.md. This data is suitable for integration testing.
        
        Returns:
            Dictionary containing all generated data with keys:
            - groups: List of 2 group dictionaries
            - tokens: Dict mapping token_id to list of (group_guid, permissions)
            - sources: List of 3 source dictionaries
            - documents: List of 10 document dictionaries
        
        Example:
            >>> store = DataStore(base_path=tmp_path)
            >>> store.setup()
            >>> data = store.generate_sample_data()
            >>> len(data['groups'])
            2
            >>> len(data['documents'])
            10
        """
        if not self.is_setup:
            self.setup()
        
        now = datetime.now()
        now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Generate fixed GUIDs for reproducibility in tests
        group_guids = [
            "g1000000-0000-0000-0000-000000000001",
            "g2000000-0000-0000-0000-000000000002",
        ]
        
        token_ids = [
            "t1000000-0000-0000-0000-000000000001",
            "t2000000-0000-0000-0000-000000000002",
            "t3000000-0000-0000-0000-000000000003",
        ]
        
        source_guids = [
            "s1000000-0000-0000-0000-000000000001",
            "s2000000-0000-0000-0000-000000000002",
            "s3000000-0000-0000-0000-000000000003",
        ]
        
        # Create 2 groups
        groups = [
            {
                "group_guid": group_guids[0],
                "name": "APAC Research",
                "description": "Asia-Pacific research team documents",
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": now_iso,
                "active": True,
                "tokens": {
                    token_ids[0]: ["create", "read", "update", "delete"],  # Admin
                    token_ids[1]: ["read"],  # Read-only
                },
                "metadata": {
                    "region": "APAC",
                    "department": "Research",
                },
            },
            {
                "group_guid": group_guids[1],
                "name": "Global Equities",
                "description": "Global equities research documents",
                "created_at": "2025-01-15T00:00:00Z",
                "updated_at": now_iso,
                "active": True,
                "tokens": {
                    token_ids[0]: ["create", "read", "update"],  # Admin (no delete)
                    token_ids[2]: ["create", "read"],  # Contributor
                },
                "metadata": {
                    "region": "Global",
                    "department": "Equities",
                },
            },
        ]
        
        # Create 3 sources (2 in group 1, 1 in group 2)
        sources = [
            {
                "source_guid": source_guids[0],
                "group_guid": group_guids[0],
                "name": "Reuters APAC",
                "type": "news_agency",
                "region": "APAC",
                "languages": ["en", "zh", "ja"],
                "trust_level": "high",
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": now_iso,
                "active": True,
                "metadata": {
                    "feed_url": "https://reuters.com/apac",
                    "update_frequency": "realtime",
                },
            },
            {
                "source_guid": source_guids[1],
                "group_guid": group_guids[0],
                "name": "Bloomberg Asia",
                "type": "news_agency",
                "region": "APAC",
                "languages": ["en"],
                "trust_level": "high",
                "created_at": "2025-02-01T00:00:00Z",
                "updated_at": now_iso,
                "active": True,
                "metadata": {
                    "feed_url": "https://bloomberg.com/asia",
                    "update_frequency": "realtime",
                },
            },
            {
                "source_guid": source_guids[2],
                "group_guid": group_guids[1],
                "name": "Internal Research",
                "type": "internal",
                "region": "Global",
                "languages": ["en"],
                "trust_level": "medium",
                "created_at": "2025-03-01T00:00:00Z",
                "updated_at": now_iso,
                "active": True,
                "metadata": {
                    "department": "Research",
                    "update_frequency": "daily",
                },
            },
        ]
        
        # Token mapping: token_id -> [(group_guid, permissions), ...]
        tokens = {
            token_ids[0]: [
                (group_guids[0], ["create", "read", "update", "delete"]),
                (group_guids[1], ["create", "read", "update"]),
            ],
            token_ids[1]: [
                (group_guids[0], ["read"]),
            ],
            token_ids[2]: [
                (group_guids[1], ["create", "read"]),
            ],
        }
        
        # Create 10 documents (7 in group 1, 3 in group 2)
        documents = self._generate_sample_documents(
            group_guids=group_guids,
            source_guids=source_guids,
            now=now,
        )
        
        return {
            "groups": groups,
            "tokens": tokens,
            "sources": sources,
            "documents": documents,
            "group_guids": group_guids,
            "token_ids": token_ids,
            "source_guids": source_guids,
        }
    
    def _generate_sample_documents(
        self,
        group_guids: list[str],
        source_guids: list[str],
        now: datetime,
    ) -> list[dict]:
        """Generate 10 sample documents with varied characteristics.
        
        Creates documents with different:
        - Languages (en, zh, ja)
        - Impact scores (critical to minimal)
        - Event types
        - Horizon times (past, imminent, future)
        """
        from datetime import timedelta
        
        doc_guids = [f"d{i:07d}-0000-0000-0000-000000000001" for i in range(1, 11)]
        
        # Sample document templates
        docs_data = [
            # Group 1 documents (7 total) - APAC Research
            {
                "title": "TSMC Reports Record Q4 Earnings",
                "content": "Taiwan Semiconductor Manufacturing Company (TSMC) reported record quarterly earnings, driven by strong AI chip demand. Revenue increased 35% year-over-year, exceeding analyst expectations. The company raised its capital expenditure guidance for 2026.",
                "language": "en",
                "impact_score": "high",
                "event_types": ["EARNINGS"],
                "tags": ["semiconductors", "AI", "taiwan"],
                "companies": [{"ticker": "2330.TW", "name": "TSMC", "relevance": 0.95}],
                "horizon_days": 7,  # Earnings impact window
                "group_idx": 0,
                "source_idx": 0,
            },
            {
                "title": "中国央行降息25个基点",
                "content": "中国人民银行宣布下调贷款市场报价利率（LPR）25个基点，以刺激经济增长。这是今年以来的第三次降息，反映出政策制定者对经济放缓的担忧。",
                "language": "zh",
                "impact_score": "critical",
                "event_types": ["MACRO", "REGULATORY"],
                "tags": ["monetary-policy", "china", "interest-rates"],
                "companies": [],
                "horizon_days": 1,  # Immediate impact
                "group_idx": 0,
                "source_idx": 0,
            },
            {
                "title": "Sony Announces Acquisition of Game Studio",
                "content": "Sony Group announced the acquisition of a major game development studio for $3.2 billion, expanding its PlayStation content portfolio. The deal is expected to close in Q2 2026 pending regulatory approval.",
                "language": "en",
                "impact_score": "medium",
                "event_types": ["M&A"],
                "tags": ["gaming", "media", "japan"],
                "companies": [
                    {"ticker": "6758.T", "name": "Sony Group", "relevance": 0.9},
                ],
                "horizon_days": 90,  # Q2 2026 close
                "group_idx": 0,
                "source_idx": 1,
            },
            {
                "title": "日本銀行、金融政策を維持",
                "content": "日本銀行は金融政策決定会合で、現行の金融緩和政策を維持することを決定した。植田総裁は、インフレ見通しに基づき、段階的な政策正常化を継続する方針を示した。",
                "language": "ja",
                "impact_score": "high",
                "event_types": ["MACRO"],
                "tags": ["monetary-policy", "japan", "boj"],
                "companies": [],
                "horizon_days": 30,
                "group_idx": 0,
                "source_idx": 0,
            },
            {
                "title": "Samsung Electronics Faces Regulatory Probe",
                "content": "South Korean regulators have launched an investigation into Samsung Electronics' memory chip pricing practices. The probe could result in significant fines if anticompetitive behavior is confirmed.",
                "language": "en",
                "impact_score": "medium",
                "event_types": ["REGULATORY", "LEGAL"],
                "tags": ["semiconductors", "korea", "antitrust"],
                "companies": [
                    {"ticker": "005930.KS", "name": "Samsung Electronics", "relevance": 0.95},
                ],
                "horizon_days": 180,  # Investigation timeline
                "group_idx": 0,
                "source_idx": 1,
            },
            {
                "title": "Alibaba Cloud Expands APAC Data Centers",
                "content": "Alibaba Cloud announced plans to open three new data centers across Southeast Asia by 2026, investing $2 billion to meet growing demand for cloud services in the region.",
                "language": "en",
                "impact_score": "low",
                "event_types": ["CAPITAL", "PRODUCT"],
                "tags": ["cloud", "infrastructure", "china"],
                "companies": [
                    {"ticker": "BABA", "name": "Alibaba Group", "relevance": 0.85},
                ],
                "horizon_days": 365,
                "group_idx": 0,
                "source_idx": 0,
            },
            {
                "title": "Weekly APAC Market Summary",
                "content": "Regional markets ended the week mixed, with Japanese equities outperforming on yen weakness while Chinese stocks retreated on property sector concerns. Trading volumes remained below average.",
                "language": "en",
                "impact_score": "minimal",
                "event_types": [],
                "tags": ["market-summary", "weekly"],
                "companies": [],
                "horizon_days": -7,  # Past event
                "group_idx": 0,
                "source_idx": 1,
            },
            # Group 2 documents (3 total) - Global Equities
            {
                "title": "Apple Unveils Next-Gen AI Features",
                "content": "Apple Inc. announced new AI-powered features for its upcoming iPhone release, including advanced on-device language models. The announcement positions Apple to compete more directly with Google and Microsoft in the AI space.",
                "language": "en",
                "impact_score": "medium",
                "event_types": ["PRODUCT"],
                "tags": ["AI", "consumer-tech", "usa"],
                "companies": [
                    {"ticker": "AAPL", "name": "Apple Inc", "relevance": 0.95},
                    {"ticker": "GOOGL", "name": "Alphabet", "relevance": 0.3},
                    {"ticker": "MSFT", "name": "Microsoft", "relevance": 0.3},
                ],
                "horizon_days": 60,
                "group_idx": 1,
                "source_idx": 2,
            },
            {
                "title": "Global ESG Fund Flows Hit Record",
                "content": "ESG-focused equity funds saw record inflows of $45 billion in November, driven by institutional investor demand for sustainable investments. European funds led the inflows.",
                "language": "en",
                "impact_score": "low",
                "event_types": ["ESG"],
                "tags": ["ESG", "fund-flows", "institutional"],
                "companies": [],
                "horizon_days": -14,  # Past data
                "group_idx": 1,
                "source_idx": 2,
            },
            {
                "title": "Fed Signals Rate Path Uncertainty",
                "content": "Federal Reserve officials indicated increased uncertainty about the pace of future rate cuts, citing persistent inflation concerns. Markets adjusted expectations for fewer cuts in 2026.",
                "language": "en",
                "impact_score": "high",
                "event_types": ["MACRO"],
                "tags": ["fed", "interest-rates", "usa"],
                "companies": [],
                "horizon_days": 45,
                "group_idx": 1,
                "source_idx": 2,
            },
        ]
        
        documents = []
        for i, doc_data in enumerate(docs_data):
            horizon_time = None
            if doc_data["horizon_days"] is not None:
                horizon_dt = now + timedelta(days=doc_data["horizon_days"])
                horizon_time = horizon_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            
            # Stagger creation times
            created_at = now - timedelta(hours=i * 6)
            
            doc = {
                "guid": doc_guids[i],
                "version": 1,
                "previous_version_guid": None,
                "source_guid": source_guids[doc_data["source_idx"]],
                "group_guid": group_guids[doc_data["group_idx"]],
                "created_at": created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "language": doc_data["language"],
                "language_detected": True,
                "title": doc_data["title"],
                "content": doc_data["content"],
                "word_count": len(doc_data["content"].split()),
                "duplicate_of": None,
                "duplicate_score": 0.0,
                "impact_score": doc_data["impact_score"],
                "horizon_time": horizon_time,
                "extracted": {
                    "event_types": doc_data["event_types"],
                    "tags": doc_data["tags"],
                    "companies": doc_data["companies"],
                    "sectors": [],
                    "regions": [],
                },
                "metadata": {
                    "author": None,
                    "original_url": None,
                    "published_at": created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            }
            documents.append(doc)
        
        return documents
    
    def write_sample_data(self, data: Optional[dict] = None) -> dict:
        """Generate sample data and write it to disk.
        
        Creates all groups, sources, and documents as JSON files in the
        appropriate directories.
        
        Args:
            data: Pre-generated data dict, or None to generate new data.
        
        Returns:
            The data dictionary that was written.
        """
        if data is None:
            data = self.generate_sample_data()
        
        # Write groups
        for group in data["groups"]:
            path = self.get_group_path(group["group_guid"])
            self.write_json(path, group)
        
        # Write sources
        for source in data["sources"]:
            path = self.get_source_path(source["group_guid"], source["source_guid"])
            self.write_json(path, source)
        
        # Write documents
        for doc in data["documents"]:
            created_at = datetime.fromisoformat(doc["created_at"].replace("Z", "+00:00"))
            path = self.get_document_path(
                doc["group_guid"],
                doc["guid"],
                date=created_at,
            )
            self.write_json(path, doc)
        
        return data
    
    def __enter__(self) -> "DataStore":
        """Context manager entry - sets up the data store."""
        return self.setup()
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - tears down the data store."""
        self.teardown(remove_all=False)
    
    def __repr__(self) -> str:
        return f"DataStore(base_path={self.base_path!r}, is_setup={self.is_setup})"
