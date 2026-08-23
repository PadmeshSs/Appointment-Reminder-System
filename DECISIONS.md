
---

# 3. `DECISIONS.md` — Chapter 14 additions

Your existing `DECISIONS.md` already contains the detailed data findings, architecture decisions, and Chapter 12/13 decisions. The missing Chapter 14 requirement is the explicit **edge-case inventory + limitations**.

Append this:

```markdown
## Chapter 14 — Documentation and demo

### Stack

- Python for the implementation and CLI.
- Standard-library Python for the production system.
- `pytest` for behavioural and integration tests.
- JSONL for append-only runtime contact history.
- Bash for the reproducible six-section demonstration.

The project deliberately remains a CLI application. A web interface would add
surface area without improving the evidence required by the problem.

### What I found in the contact list

The supplied contact list contains structural ambiguity rather than primarily
malformed data.

| Edge case | Finding | Decision |
|---|---:|---|
| No contact details | 14 residents | Report as unreachable; do not invent contact information |
| Fully opted out | 11 residents | Respect all channel opt-outs |
| No mobile | 62 residents | Use another permitted channel where policy allows |
| No landline | 407 residents | Do not assume voice is always available |
| No email | 258 residents | Do not assume email is always available |
| Shared mobile numbers | 27 numbers / 61 residents | Keep residents separate; protect the shared point |
| Shared email addresses | 69 addresses / 151 residents | Treat identical-name clusters as suspected duplicate humans |
| Conflicting language in identity clusters | 35 clusters | Do not merge automatically |
| Conflicting opt-outs in identity clusters | 29 clusters | Do not merge automatically |
| Suspected landline numbers in mobile field | 41 | Use the signal to reorder/protect channels; do not blindly trust the CSV label |
| Verification older than one year | 382 residents | Treat as uncertainty, not proof of invalidity |
| Verification older than two years | 126 residents | Same treatment; do not automatically discard |
| Appointment range | 2–31 March 2026 | Treat the CSV as authoritative |
| Malformed phones | 0 | No cleaning rule required |
| Malformed emails | 0 | No cleaning rule required |
| Orphan appointments | 0 | No repair required |
| Duplicate resident IDs | 0 | No repair required |

### The harm case

The most important structural risk is that multiple resident records can
represent the same human.

The regulator's contact limit is correctly keyed by `resident_id`, so that rule
must remain unchanged. However, the suspected identity clusters demonstrate
that resident-level counting alone can understate contact frequency to one
human.

The identity guard is therefore a separate protection. It does not merge
records because duplicate records can contain contradictory language and
opt-out information.

The final March run reduced the maximum observed suspected-person contact count
from 6 to 2.

### Stale numbers

A stale verification date is not treated as proof that a contact point is
invalid.

Automatically discarding stale contact points would create an unsupported
assumption that old data is wrong. Instead, the audit reports verification
staleness and the policy continues to use contactability rules based on the
available evidence.

### The landline trap

Some numbers appear in the `mobile` field even though their prefixes match
landline exchanges observed elsewhere in the county data.

The system does not simply trust the CSV column.

The suspected-landline signal influences channel ordering and outcome
interpretation. A carrier response such as `delivered` with
`accepted_by_carrier` is not treated as human reach.

### Two people, one phone

Shared mobile numbers do not automatically mean duplicate residents.

Where two residents genuinely share a contact point, they remain separate
residents and receive separately addressed messages.

The contact point has its own protection against excessive daily messaging and
duplicate message bodies.

The resident-level rolling contact count remains associated with the resident
who was actually contacted.

### Language

The system selects a template from the resident's requested language.

If a template does not exist, it falls back to English and records the fallback
rather than silently pretending the requested language was supported.

The system does not use an external translation service or an LLM to generate
translations.

### The stopping rule

The system has explicit attempt, retry, quiet-hour, contact-point, daily, and
rolling contact protections.

A human answering a voice call stops further reminder attempts.

The adaptive stopping rule described as optional in the problem was not
implemented.

This was a conscious scope decision: the explicit floor requirements were
prioritised over the optional adaptive rule.

### Day two

Direction CR-2026/11 was implemented as a policy-layer retrofit.

The existing resident-keyed append-only ledger made the change small because
failed attempts were already recorded as contacts.

Retrospective history is imported through `--seed-history`.

The identity guard is separate from the regulator's resident-level counter and
does not merge suspected duplicate records.

The final enforced March run produced zero compliance breaches.

### What this does not do

The following limitations are explicit.

- **No adaptive stopping rule.** The system uses fixed attempt and timing
  limits rather than learning when another attempt is unlikely to help.
- **No explicit cost model for the two errors.** The system measures confirmed
  reach, coverage gap, and harm ceiling, but it does not assign a monetary or
  service cost to a missed reminder versus an unwanted reminder.
- **No reconciliation of contradictory duplicate records.** The identity guard
  protects suspected duplicate humans but does not decide which record is the
  correct one. Human review is required.
- **One cadence for every service type.** The reminder timing rules are not
  specialised for different appointment or service categories.
- **Approximately 26 residents remain permanently unreachable.** The system
  reports the absence of contactability rather than inventing contact details
  or silently changing the supplied data.
- **No real identity-resolution system.** `identity_key` is a risk signal, not
  proof of legal or real-world identity.
- **No guarantee of human reading for SMS or email.** Technical delivery is
  deliberately not treated as confirmed human reach.
- **No automatic correction of stale contact information.** Staleness is
  reported as uncertainty rather than treated as proof of invalidity.

These are known boundaries of the system rather than hidden failures.