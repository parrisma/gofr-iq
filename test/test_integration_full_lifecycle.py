import pytest
import requests
from app.auth import AuthService

@pytest.mark.integration
def test_full_lifecycle(shared_server_manager, infra_available):
    """
    Test full lifecycle:
    1. Start servers (handled by fixture).
    2. Ingest document via Web API.
    3. Verify document via Web API (read path).
    
    This satisfies Requirement D: Integration tests that prove full lifecycle.
    """
    if not shared_server_manager.is_running:
        pytest.skip("Servers not running")

    web_url = shared_server_manager.web_url
    print(f"Testing against Web URL: {web_url}")
    
    # Generate Auth Token
    # The server manager uses the secret from env or default
    jwt_secret = shared_server_manager.jwt_secret
    auth_service = AuthService(secret_key=jwt_secret)
    # Fix: create_token expects group: str
    token = auth_service.create_token(group="test-group-1")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Ingest Document
    ingest_url = f"{web_url}/ingest"
    payload = {
        "title": "Test Document Lifecycle",
        "content": "This is a test document for full lifecycle integration.",
        "source_guid": "test-source-lifecycle",
        "group_guid": "test-group-1",
        "language": "en",
        "metadata": {"test": True}
    }
    
    print(f"Ingesting document to {ingest_url}...")
    try:
        response = requests.post(ingest_url, json=payload, headers=headers)
        assert response.status_code == 200, f"Ingest failed: {response.text}"
        data = response.json()
        assert data["status"] == "success"
        doc_guid = data["data"]["guid"]
        print(f"Document ingested with GUID: {doc_guid}")
    except requests.exceptions.ConnectionError:
        pytest.fail(f"Could not connect to Web Server at {ingest_url}. Is it running?")

    # 2. Verify via Document Store (Read Path)
    get_url = f"{web_url}/documents/get"
    get_payload = {
        "guid": doc_guid,
        "group_guid": "test-group-1"
    }
    
    print(f"Retrieving document from {get_url}...")
    response = requests.post(get_url, json=get_payload, headers=headers)
    assert response.status_code == 200, f"Get document failed: {response.text}"
    doc_data = response.json()
    assert doc_data["status"] == "success"
    assert doc_data["data"]["guid"] == doc_guid
    assert doc_data["data"]["title"] == "Test Document Lifecycle"
    
    print("Full lifecycle test passed!")
