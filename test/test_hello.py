"""Simple hello world test for gofr-iq"""


def test_hello_world():
    """Basic test to verify pytest is working"""
    assert True


def test_app_import():
    """Test that the app package can be imported"""
    import app
    assert app.__version__ == "0.1.0"


def test_gofr_common_import():
    """Test that gofr_common can be imported"""
    import gofr_common
    assert gofr_common.__version__ is not None


def test_config_import():
    """Test that app.config can be imported with GOFR_IQ prefix"""
    from app.config import Config
    assert Config._env_prefix == "GOFR_IQ"
