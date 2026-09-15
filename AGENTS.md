# fossil-demo agent rules

This repository is the product shell around `Pukujan/fossil-core`.

## Authority boundary

- `fossil-demo` owns anonymous sessions, temporary workspace lifecycle, quotas, UI-oriented aggregation, and product-facing HTTP behavior.
- `fossil-core` owns completeness, content identity, provenance, citations, lifecycle, lineage, durable event semantics, pack authority, and projection authority.
- Never make an HTTP/job success imply FOSSIL semantic success.
- Incomplete/unknown capture may preserve evidence while promotion is refused.
- Never label structural reconstructed lineage as semantic claims/decisions.

## Security invariants

- Workspace ID is never a credential.
- Every workspace operation is scoped by both workspace ID and anonymous-session ownership.
- Session secrets stay in Secure/HttpOnly/SameSite=Strict cookies; persist only their hashes.
- Never accept arbitrary filesystem paths, artifact IDs, or workspace roots from the client as authority.
- Keep workspace paths server-generated and root-confined.
- Raw/private source content must not be committed to this public repository.

## V0 scope

Until #4 is complete, the only supported source input is a public ChatGPT share URL. Fixtures are allowed behind the capture adapter to prove the product contract before live FOSSIL wiring.
