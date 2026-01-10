# GOFR-IQ Authentication Architecture Review

## Findings & Analysis

### 1. Token & Group Management (Infrastructure Support)

The `gofr-common` library provides a robust foundation for authentication, specifically designed to interoperate with HashiCorp Vault.

*   **Group Registry:** `lib/gofr-common/src/gofr_common/auth/groups.py` implements a pluggable `GroupRegistry` that supports memory, file, and Vault backends. It handles reserved groups (`public`, `admin`) correctly, preventing their deletion.
*   **Token Service:** `lib/gofr-common/src/gofr_common/auth/service.py` provides `AuthService` for JWT creation and validation, supporting multi-group tokens (v2 auth).
*   **CLI Tools:** `lib/gofr-common/scripts/auth_manager.py` offers a comprehensive CLI for managing groups and tokens, handling CRUD operations and inspection.
*   **Bootstrap:** `lib/gofr-common/scripts/bootstrap_auth.py` is idempotent and ensures reserved groups exist and creates initial tokens. This aligns perfectly with requirement #3 ("bootstrap script in lib/gofr-common/scripts").

### 2. Service Integration

The integration of authentication into GOFR-IQ services follows the expected pattern, using `GroupService` as the bridge.

*   **Group Service:** `app/services/group_service.py` acts as the central point for auth logic within the application. It provides helper methods like `resolve_permitted_groups` and `resolve_write_group` which handle both explicit token parameters (for proxy scenarios) and context headers (for direct usage).
*   **Context Awareness:** the service correctly extracts authentication context from request headers via `get_auth_header_from_context`, enabling seamless auth flow in the MCP server.

### 3. Source Management (Requirement #7)

Source management tools enforce authentication and group-based access control.

*   **Creation:** `create_source` in `app/tools/source_tools.py` requires a valid write token. It resolves the write group from the token and assigns the new source to that group. This matches requirement #7 ("Sources are then created using the admin token").
*   **Access Control:** `list_sources` and `get_source` filter results based on the user's permitted groups.
*   **CLI:** `scripts/manage_source.sh` provides a convenient wrapper for calling these MCP tools, simulating a client interacting with the system.

### 4. Document Ingestion (Requirements #8 & #9)

Document ingestion logic respects group boundaries.

*   **Ingestion:** `ingest_document` in `app/tools/ingest_tools.py` mandates authentication for write operations. It writes documents to the primary group of the provided token. This satisfies requirement #9 ("documents can then be injested from specific sources into specific user groups").
*   **Storage:** The `DocumentStore` organizes files physically by group GUID (`documents/{group_guid}/{date}/{guid}.json`), ensuring strong data segregation at the storage level.

### 5. Query Service (Requirement #10)

The query engine implements strict group-scoped searching.

*   **Search:** `QueryService.query` in `app/services/query_service.py` takes a list of `group_guids`.
*   **Tooling:** `query_documents` in `app/tools/query_tools.py` automatically resolves the user's permitted groups (token groups + public) and passes them to the service layer.
*   **Hybrid Search:** Both semantic search (ChromaDB) and graph expansion (Neo4j) respect these group boundaries, ensuring users never see content they don't have access to. This meets requirement #10 ("documents can be quieried... see groups defined for the token + public group").

### 6. Admin Access (Requirement #5 & #6)

Admin capabilities are implemented via specific group memberships.

*   **Admin Group:** The `admin` group is a reserved concept. While specific "admin actions" like system maintenance are audited, general admin access to data is handled by simply having the `admin` group in your token.
*   **Broad Access:** An admin token allows reading/writing to the `admin` group. However, the system design (Group Access Control) implies that for an admin to see *everything*, they might need a token with a superset of groups or specific logic (like `check_permission` in `group_access.py`) which acts as a superuser check. The current implementation relies heavily on group-based filtering.

## Verification of Requirements

| Requirement | Status | Implementation Details |
| :--- | :---: | :--- |
| 1. Shared groups created in Auth service | ✅ | `bootstrap_auth.py` creates `public` and `admin` groups in the configured backend (Vault supported). |
| 2. Shared tokens created in Auth service | ✅ | `bootstrap_auth.py` generates long-lived tokens for `public` and `admin` groups. |
| 3. Done by bootstrap script | ✅ | `lib/gofr-common/scripts/bootstrap_auth.py` handles this. |
| 4. Checked using auth_manager.sh | ✅ | `auth_manager.sh` exposes `groups list` and `tokens list` to verify state. |
| 5. Services passed Admin JWT | ✅ | Tools and services accept `auth_tokens` or read headers. Scripts like `manage_source.sh` accept token args. |
| 6. Admin token maps to admin group | ✅ | `AuthService` verifies token and extracts `["admin"]` group. |
| 7. Sources created using admin token | ✅ | `create_source` tool uses the token's group (admin) as the owner of the new source. |
| 8. User groups created to segregate data | ✅ | `GroupRegistry` supports creating arbitrary groups. Documents/sources are scoped to these groups. |
| 9. Documents ingested to specific groups | ✅ | `ingest_document` writes to the token's primary group. |
| 10. Documents queried by token groups | ✅ | `query_documents` filters results by the set of groups in the user's token + `public`. |

## Conclusion

The GOFR-IQ authentication implementation aligns with the specified design requirements. The architecture correctly segregates data by groups, enforces access controls at the service entry points (MCP tools), and leverages a centralized authentication service backed by Vault (or other providers) via `gofr-common`. The bootstrap and management scripts provide the necessary operational tooling to maintain this security model.
