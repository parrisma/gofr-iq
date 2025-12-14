
import argparse
import requests
from test.test_articles import get_test_articles

def inject_all_stories_via_mcpo(mcpo_url: str, test_groups: dict) -> None:
    """
    Helper function to inject all test stories into the system via MCPO REST API.
    Assumes MCPO is running and accessible at the given URL.
    """
    articles = get_test_articles(test_groups)
    for idx, article in enumerate(articles, 1):
        payload = {
            "title": article.title,
            "content": article.content,
            "group_guid": article.group_guid,
            "impact_score": article.impact_score,
            "impact_tier": article.impact_tier,
            "event_type": article.event_type,
            "instruments": article.instruments,
            "companies": article.companies,
        }
        try:
            resp = requests.post(f"{mcpo_url}/api/ingest", json=payload, timeout=10)
            resp.raise_for_status()
            print(f"[{idx}/{len(articles)}] Injected: {article.title}")
        except Exception as e:
            print(f"[{idx}/{len(articles)}] Failed: {article.title} | Error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject all test stories into MCPO via REST API.")
    parser.add_argument("--mcpo-url", type=str, required=True, help="Base URL for MCPO (e.g. http://localhost:8080)")
    args = parser.parse_args()

    # Define test groups (should match those used in test_articles.py)
    from types import SimpleNamespace
    TEST_GROUPS = {
        "A": SimpleNamespace(guid="aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"),
        "B": SimpleNamespace(guid="bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"),
        "C": SimpleNamespace(guid="cccccccc-cccc-4ccc-cccc-cccccccccccc"),
    }

    inject_all_stories_via_mcpo(args.mcpo_url, TEST_GROUPS)
