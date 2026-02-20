"""Tests for bootstrap authentication tokens.

These tests verify that the bootstrap_auth fixture in conftest.py correctly
creates public and admin tokens that can be used for authentication.

NOTE: Tokens are now created by the `bootstrap_auth` session fixture in conftest.py,
not by an external script. They are always available when running via run_tests.sh.
"""

import os

import jwt


class TestBootstrapTokens:
    """Test bootstrap token creation and validity."""

    def test_public_token_exists(self, public_token: str) -> None:
        """Verify public token is created by bootstrap_auth fixture."""
        assert public_token is not None
        assert len(public_token) > 0
        assert public_token.count(".") == 2  # JWT has 3 parts

    def test_admin_token_exists(self, admin_token: str) -> None:
        """Verify admin token is created by bootstrap_auth fixture."""
        assert admin_token is not None
        assert len(admin_token) > 0
        assert admin_token.count(".") == 2  # JWT has 3 parts

    def test_public_token_has_public_group(self, public_token: str) -> None:
        """Verify public token contains the 'public' group."""
        jwt_secret = os.environ.get("GOFR_IQ_JWT_SECRET") or os.environ.get("GOFR_JWT_SECRET")
        assert jwt_secret, "GOFR_IQ_JWT_SECRET or GOFR_JWT_SECRET must be set"
        
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

    def test_admin_token_has_admin_group(self, admin_token: str) -> None:
        """Verify admin token contains the 'admin' group."""
        jwt_secret = os.environ.get("GOFR_IQ_JWT_SECRET") or os.environ.get("GOFR_JWT_SECRET")
        assert jwt_secret, "GOFR_IQ_JWT_SECRET or GOFR_JWT_SECRET must be set"
        
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
        public_token: str,
        admin_token: str,
    ) -> None:
        """Verify public and admin tokens are distinct."""
        assert public_token != admin_token

    def test_public_token_verifiable_with_auth_service(
        self,
        public_token: str,
        vault_auth_service,
    ) -> None:
        """Verify public token can be validated by AuthService."""
        # Verify token through auth service
        token_info = vault_auth_service.verify_token(public_token)
        
        assert token_info is not None
        assert "public" in token_info.groups

    def test_admin_token_verifiable_with_auth_service(
        self,
        admin_token: str,
        vault_auth_service,
    ) -> None:
        """Verify admin token can be validated by AuthService."""
        # Verify token through auth service
        token_info = vault_auth_service.verify_token(admin_token)
        
        assert token_info is not None
        assert "admin" in token_info.groups
