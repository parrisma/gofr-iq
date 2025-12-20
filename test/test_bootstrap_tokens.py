"""Tests for bootstrap authentication tokens.

These tests verify that the bootstrap_auth.py script correctly creates
public and admin tokens that can be used for authentication.
"""

import os

import jwt
import pytest


class TestBootstrapTokens:
    """Test bootstrap token creation and validity."""

    def test_public_token_exists(self, public_token: str | None) -> None:
        """Verify public token is available from environment."""
        # This test will pass if run via run_tests.sh which exports the token
        # It may be None if run directly without the bootstrap
        if public_token is None:
            pytest.skip("GOFR_IQ_PUBLIC_TOKEN not set (run via run_tests.sh)")
        
        assert public_token is not None
        assert len(public_token) > 0
        assert public_token.count(".") == 2  # JWT has 3 parts

    def test_admin_token_exists(self, admin_token: str | None) -> None:
        """Verify admin token is available from environment."""
        if admin_token is None:
            pytest.skip("GOFR_IQ_ADMIN_TOKEN not set (run via run_tests.sh)")
        
        assert admin_token is not None
        assert len(admin_token) > 0
        assert admin_token.count(".") == 2  # JWT has 3 parts

    def test_public_token_has_public_group(self, public_token: str | None) -> None:
        """Verify public token contains the 'public' group."""
        if public_token is None:
            pytest.skip("GOFR_IQ_PUBLIC_TOKEN not set")
        
        jwt_secret = os.environ.get(
            "GOFR_IQ_JWT_SECRET",
            "test-secret-key-for-secure-testing-do-not-use-in-production"
        )
        
        payload = jwt.decode(
            public_token,
            jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        
        assert "groups" in payload
        assert payload["groups"] == ["public"]
        assert "jti" in payload  # Token ID
        assert "exp" in payload  # Expiry

    def test_admin_token_has_admin_group(self, admin_token: str | None) -> None:
        """Verify admin token contains the 'admin' group."""
        if admin_token is None:
            pytest.skip("GOFR_IQ_ADMIN_TOKEN not set")
        
        jwt_secret = os.environ.get(
            "GOFR_IQ_JWT_SECRET",
            "test-secret-key-for-secure-testing-do-not-use-in-production"
        )
        
        payload = jwt.decode(
            admin_token,
            jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        
        assert "groups" in payload
        assert payload["groups"] == ["admin"]
        assert "jti" in payload
        assert "exp" in payload

    def test_tokens_are_different(
        self,
        public_token: str | None,
        admin_token: str | None,
    ) -> None:
        """Verify public and admin tokens are distinct."""
        if public_token is None or admin_token is None:
            pytest.skip("Bootstrap tokens not set")
        
        assert public_token != admin_token

    def test_public_token_verifiable_with_auth_service(
        self,
        public_token: str | None,
        vault_auth_service,
    ) -> None:
        """Verify public token can be validated by AuthService."""
        if public_token is None:
            pytest.skip("GOFR_IQ_PUBLIC_TOKEN not set")
        
        # Verify token through auth service
        token_info = vault_auth_service.verify_token(public_token)
        
        assert token_info is not None
        assert "public" in token_info.groups

    def test_admin_token_verifiable_with_auth_service(
        self,
        admin_token: str | None,
        vault_auth_service,
    ) -> None:
        """Verify admin token can be validated by AuthService."""
        if admin_token is None:
            pytest.skip("GOFR_IQ_ADMIN_TOKEN not set")
        
        # Verify token through auth service
        token_info = vault_auth_service.verify_token(admin_token)
        
        assert token_info is not None
        assert "admin" in token_info.groups
