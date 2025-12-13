"""GOFR-IQ Web Server Implementation.

Provides REST API endpoints for the APAC Brokerage News Repository.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from gofr_common.web import CORSConfig
from pydantic import BaseModel, Field

from app.auth import (
    AuthService,
    TokenInfo,
    init_auth_service,
    optional_verify_token,
    verify_token,
)
from app.config import get_settings
from app.logger import ConsoleLogger
from app.models import SourceType
from app.services import (
    DocumentStore,
    DuplicateDetector,
    EmbeddingIndex,
    GraphIndex,
    IngestService,
    LanguageDetector,
    SourceRegistry,
)


# Request/Response Models
class IngestDocumentRequest(BaseModel):
    """Request model for document ingestion"""

    title: str = Field(..., description="Document title")
    content: str = Field(..., description="Document content")
    source_guid: str = Field(..., description="Source GUID")
    group_guid: str = Field(..., description="Group GUID for access control")
    language: Optional[str] = Field(None, description="Language code (auto-detected if not provided)")
    metadata: Optional[dict[str, Any]] = Field(None, description="Additional metadata")


class ListSourcesRequest(BaseModel):
    """Request model for listing sources"""

    group_guid: Optional[str] = Field(None, description="Filter by group GUID")
    region: Optional[str] = Field(None, description="Filter by region")
    source_type: Optional[SourceType] = Field(None, description="Filter by source type")
    include_inactive: bool = Field(False, description="Include inactive sources")


class GetSourceRequest(BaseModel):
    """Request model for getting a source"""

    source_guid: str = Field(..., description="Source GUID")
    group_guid: Optional[str] = Field(None, description="Group GUID for access control")


class GetDocumentRequest(BaseModel):
    """Request model for getting a document"""

    guid: str = Field(..., description="Document GUID")
    group_guid: str = Field(..., description="Group GUID for access control")
    date_hint: Optional[str] = Field(None, description="Date hint for partitioned storage (YYYY-MM-DD)")


class GofrIqWebServer:
    """FastAPI Web Server for GOFR-IQ."""

    def __init__(
        self,
        storage_dir: str | Path | None = None,
        jwt_secret: Optional[str] = None,
        token_store_path: Optional[str] = None,
        require_auth: bool = True,
        auth_service: Optional[AuthService] = None,
        log_level: int = logging.INFO,
    ):
        """Initialize GofrIqWebServer.

        Args:
            storage_dir: Override storage directory (uses config if not provided)
            jwt_secret: JWT secret key (deprecated - use auth_service instead)
            token_store_path: Path to token store (deprecated - use auth_service instead)
            require_auth: Whether authentication is required
            auth_service: AuthService instance (preferred - enables dependency injection)
            log_level: Logging level (logging.DEBUG, logging.INFO, etc.)
        """
        self.app = FastAPI(
            title="gofr-iq",
            description="APAC Brokerage News Repository REST API",
            version="1.23.1",
        )

        self.require_auth = require_auth
        self.logger = ConsoleLogger(name="web_server", level=log_level)

        # Get configuration
        settings = get_settings(require_auth=require_auth)
        storage_path = Path(storage_dir) if storage_dir else settings.storage.storage_dir

        # Initialize services
        self.document_store = DocumentStore(base_path=storage_path / "documents")
        self.source_registry = SourceRegistry(base_path=storage_path / "sources")
        self.language_detector = LanguageDetector()
        self.duplicate_detector = DuplicateDetector()

        # Initialize indexes
        self.embedding_index = EmbeddingIndex(
            persist_directory=storage_path / "chroma",
        )
        self.graph_index = GraphIndex()

        # Initialize ingest service
        self.ingest_service = IngestService(
            document_store=self.document_store,
            source_registry=self.source_registry,
            language_detector=self.language_detector,
            duplicate_detector=self.duplicate_detector,
            embedding_index=self.embedding_index,
            graph_index=self.graph_index,
        )

        # Configure CORS middleware
        cors_config = CORSConfig.from_env("GOFR_IQ")
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_config.allow_origins,
            allow_credentials=cors_config.allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Initialize auth service
        if require_auth:
            if auth_service is not None:
                init_auth_service(auth_service=auth_service)
            else:
                init_auth_service(secret_key=jwt_secret, token_store_path=token_store_path)

        self.logger.info(
            "Web server initialized",
            version="1.23.1",
            authentication_enabled=require_auth,
            auth_service_injected=auth_service is not None,
            storage_dir=str(storage_path),
        )

        self._setup_routes()

    def _get_auth_dependency(self):
        """Get the appropriate auth dependency based on require_auth setting"""
        return verify_token if self.require_auth else optional_verify_token

    def _setup_routes(self):
        """Setup all REST API routes"""

        @self.app.get("/ping")
        async def ping(request: Request):
            """Health check endpoint that returns the current server time."""
            return JSONResponse(
                content={
                    "status": "ok",
                    "service": "gofr-iq",
                    "timestamp": datetime.utcnow().isoformat(),
                    "version": "1.23.1",
                }
            )

        @self.app.post("/ingest")
        async def ingest_document(
            req: IngestDocumentRequest,
            token_info: Optional[TokenInfo] = Depends(self._get_auth_dependency()),
        ):
            """Ingest a news document into the repository.

            Validates source, detects language, checks for duplicates, and stores the document.
            """
            try:
                self.logger.info(
                    "Ingesting document",
                    title=req.title,
                    source_guid=req.source_guid,
                    group_guid=req.group_guid,
                    user=token_info.group if token_info else "anonymous",
                )

                result = self.ingest_service.ingest(
                    title=req.title,
                    content=req.content,
                    source_guid=req.source_guid,
                    group_guid=req.group_guid,
                    language=req.language,
                    metadata=req.metadata or {},
                )

                return JSONResponse(
                    content={
                        "status": "success",
                        "data": {
                            "guid": result.guid,
                            "language": result.language,
                            "word_count": result.word_count,
                            "is_duplicate": result.is_duplicate,
                            "created_at": result.created_at.isoformat(),
                        },
                    }
                )

            except Exception as e:
                self.logger.error("Document ingestion failed", error=str(e))
                raise HTTPException(status_code=400, detail=str(e))

        @self.app.post("/sources/list")
        async def list_sources(
            req: ListSourcesRequest,
            token_info: Optional[TokenInfo] = Depends(self._get_auth_dependency()),
        ):
            """List all registered news sources with optional filtering."""
            try:
                sources = self.source_registry.list_sources(
                    group_guid=req.group_guid,
                    region=req.region,
                    source_type=req.source_type,
                    include_inactive=req.include_inactive,
                )

                return JSONResponse(
                    content={
                        "status": "success",
                        "data": {
                            "sources": [
                                {
                                    "guid": s.source_guid,
                                    "name": s.name,
                                    "region": s.region,
                                    "source_type": s.type.value if s.type else None,
                                    "active": s.active,
                                }
                                for s in sources
                            ],
                            "count": len(sources),
                        },
                    }
                )

            except Exception as e:
                self.logger.error("Failed to list sources", error=str(e))
                raise HTTPException(status_code=400, detail=str(e))

        @self.app.post("/sources/get")
        async def get_source(
            req: GetSourceRequest,
            token_info: Optional[TokenInfo] = Depends(self._get_auth_dependency()),
        ):
            """Get detailed information about a specific news source."""
            try:
                source = self.source_registry.get(
                    source_guid=req.source_guid,
                )

                if not source:
                    raise HTTPException(status_code=404, detail=f"Source not found: {req.source_guid}")

                return JSONResponse(
                    content={
                        "status": "success",
                        "data": {
                            "guid": source.source_guid,
                            "name": source.name,
                            "region": source.region,
                            "source_type": source.type.value if source.type else None,
                            "feed_url": source.metadata.feed_url if source.metadata else None,
                            "active": source.active,
                            "metadata": source.metadata.model_dump() if source.metadata else None,
                        },
                    }
                )

            except HTTPException:
                raise
            except Exception as e:
                self.logger.error("Failed to get source", error=str(e))
                raise HTTPException(status_code=400, detail=str(e))

        @self.app.post("/documents/get")
        async def get_document(
            req: GetDocumentRequest,
            token_info: Optional[TokenInfo] = Depends(self._get_auth_dependency()),
        ):
            """Retrieve a document from the repository by its GUID."""
            try:
                document = self.ingest_service.get_document(
                    guid=req.guid,
                    group_guid=req.group_guid,
                )

                if not document:
                    raise HTTPException(status_code=404, detail=f"Document not found: {req.guid}")

                return JSONResponse(
                    content={
                        "status": "success",
                        "data": {
                            "guid": document.guid,
                            "title": document.title,
                            "content": document.content,
                            "source_guid": document.source_guid,
                            "group_guid": document.group_guid,
                            "language": document.language,
                            "word_count": document.word_count,
                            "created_at": document.created_at.isoformat(),
                            "metadata": document.metadata,
                        },
                    }
                )

            except HTTPException:
                raise
            except Exception as e:
                self.logger.error("Failed to get document", error=str(e))
                raise HTTPException(status_code=400, detail=str(e))
