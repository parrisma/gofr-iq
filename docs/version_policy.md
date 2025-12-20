Below is the **pure, plain‑text policy** you asked for. No formatting, no markup, no code fences.

---

Policy: External Service and Python Library Version Synchronization

1. All external services used by the project (for example: HashiCorp Vault, ChromaDB, Redis, Postgres, MinIO, Elasticsearch, etc.) must have their versions explicitly pinned. No floating tags such as “latest”, “stable”, or major-only tags are allowed. Every service must be defined using a full, immutable version identifier (for example: vault:1.17.3, chromadb:0.5.4, redis:7.2.4).

2. All Python libraries that communicate with these services must also be pinned to exact versions in pyproject.toml. No version ranges, no caret or tilde operators, and no wildcard versions. Every dependency must use a strict version such as “vault-cli == 0.4.1” or “chromadb == 0.5.4”.

3. The version of each Python library must be explicitly mapped to the version of the external service it supports. This mapping must be documented in a file named SERVICE_COMPATIBILITY.md at the project root. The file must contain a table listing each service, the required service version, the required Python library version, and any known compatibility notes.

4. The build pipeline must enforce compatibility by performing the following checks:
   - Parse pyproject.toml to extract pinned Python library versions.
   - Parse the service definitions (docker-compose, Helm chart, Terraform variables, or environment configuration) to extract pinned service versions.
   - Compare the extracted versions against the SERVICE_COMPATIBILITY.md table.
   - Fail the build if any mismatch is detected.

5. When upgrading a service or its associated Python library, the following workflow must be followed:
   - Upgrade the service version in the infrastructure configuration.
   - Upgrade the corresponding Python library version in pyproject.toml.
   - Update the SERVICE_COMPATIBILITY.md table.
   - Run integration tests that validate the service and library pair.
   - Only after successful tests may the change be merged.

6. No developer may upgrade a Python library or external service independently. All upgrades must be performed as coordinated pairs to prevent runtime incompatibilities.

7. The project version in pyproject.toml must be bumped whenever a service/library compatibility pair changes. This ensures that downstream consumers can detect compatibility-impacting changes.

8. The build pipeline must expose the resolved service versions and Python library versions as build metadata (for example: OCI labels on Docker images). This ensures that deployed artifacts always carry a verifiable compatibility signature.

---

If you want, I can also produce a minimal SERVICE_COMPATIBILITY.md template that fits this policy.
