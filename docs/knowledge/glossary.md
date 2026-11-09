# Glossary: AddressMatch and its three axes

Decided 2026-04-18: `Candidate` and `AddressMatch` are **synonyms** for the same entity. No rename planned — code keeps using `Candidate` / `candidates.py` / `candidates` table; conversation and new docs may use either term interchangeably.

**Why:** The team prefers "AddressMatch" as a more descriptive name in discussion, but a full rename across DB schema, Python identifiers, and templates wasn't worth the churn.

**How to apply:** Treat the two terms as equivalent. Don't "fix" existing code that says `candidate`. New code/docs can use either — match the surrounding context.

---

### Core entity
- **AddressMatch** ≡ **Candidate** — one row from the input CSV paired with its OSM lookup result. The unit flowing through the pipeline.

### Three orthogonal axes

**1. `verdict`** — what conflation decided (machine):
- `MATCH` — same housenumber+street already in OSM within near threshold; skip
- `MATCH_FAR` — same housenumber+street in OSM but unusually far; needs review
- `MISSING` — not found in OSM; eligible for upload
- `SKIPPED` — address range or duplicate; held for reference only

**2. `status`** — what the operator decided (human):
- `OPEN` — awaiting operator decision
- `APPROVED` — operator approved; will upload in next batch
- `APPROVED_override` — operator approved after pipeline auto-approved or flagged
- `REJECTED` — operator rejected; will not upload
- `REJECTED_override` — operator rejected something pipeline auto-approved
- `DEFERRED` — postponed; stays in review queue
- `AUTO_APPROVED` — pipeline auto-approved (MISSING verdict, no flags)

**3. `stage`** — where it is in the pipeline:
- `REVIEW_PENDING` — flagged by a check; awaiting decision
- `APPROVED` — cleared for upload
- `SKIPPED` — not uploading (MATCH, range, or duplicate)
- `BATCHED` — already in an upload batch

### Surrounding vocabulary

- **Run** — one execution of the pipeline; produces many AddressMatches/Candidates
- **Batch** — a bundle of APPROVED items packaged for upload
  - Statuses: `draft`, `pending`, `uploaded`, `failed`, `needs_attention`
- **Check** — a rule that flags items for review (verdicts: `FLAG`, `PASS`; severities: `warn`, `info`)
- **Tag-diff states** — `SAME` (OSM matches), `CHANGE` (proposed differs)
