# Decisions

## 1. Initial stack

- **Python, CLI:** Chosen because the project does not require a UI, as stated in the Project Handbook. 
Python's standard library is sufficient for the core implementation, with `pytest` used for testing.
- **Rejected:** A web frontend UI is rejected because it would consume time for the main core development as it focused on reminder logic and auditablility.

## 2. Data exploration

### What I found

I inspected the supplied `contacts.csv`, `appointments.csv`, and
`channels.py` using throwaway scripts in `tools/`.

The dataset contains:

- 620 residents
- 940 appointments
- Appointment dates actually range from 2–31 March 2026
- 14 residents have no contact details; 12 of them have appointments
- 11 residents are opted out of all three channels; 8 of them have appointments
- 62 residents have no mobile
- 407 residents have no landline
- 258 residents have no email

### Shared contact points

Shared contact points are not all the same kind of duplicate.

- 27 mobile numbers are shared by 61 residents.
- 26 of the 27 shared mobile numbers have different names attached to them.
- 69 email addresses are shared by 151 residents.
- All 69 shared email addresses have identical names attached to them.

Decision:

- Shared mobile numbers with different names are treated as different
  residents sharing one contact point. They must remain separately addressed.
- Shared email addresses with identical names are treated as a possible
  duplicate-human/duplicate-record situation for harm analysis.
- I will not automatically merge these records because other fields can
  disagree.

### Duplicate-name conflicts

Duplicate-name clusters revealed:

- 35 clusters with conflicting language preferences.
- 29 clusters with conflicting opt-out settings.

Decision:

I will not automatically merge duplicate-name records. Doing so could
silently select the wrong language or incorrectly override an opt-out.
These records need to remain distinguishable until there is a reliable
identity-resolution process.

### Landline trap

41 numbers recorded in the `mobile` column match exchange prefixes observed
in the county's `landline` column. 12 of these residents have no other
contact point.

I deliberately did not hardcode the mock's `555-2xx` rule. The suspected
landline signal is derived from the county's own data.

Decision:

- Use the inferred signal to reorder channels rather than suppress SMS
  outright.
- After an SMS attempt, inspect both `status` and `detail`.
- `delivered` with `accepted_by_carrier` is not treated as successful reach.
- A suspected landline should therefore be considered unsuitable for SMS
  after the carrier evidence confirms the problem.

The repeated SMS experiment showed that the mock can report a landline SMS
as `delivered` with `accepted_by_carrier`. Therefore carrier delivery is not
sufficient evidence that the resident received the message.

### Verification staleness

382 residents have verification dates older than one year and 126 are older
than two years.

Decision:

A stale verification date is treated as evidence of uncertainty, not proof
that a contact point is invalid. I will not automatically discard a contact
point solely because its verification date is old.

### Appointment dates

The data contains appointments from 2–31 March 2026.

Decision:

The actual CSV data is treated as authoritative rather than the pack README
when the two disagree.

### Data integrity

The exploration found:

- 0 malformed phones
- 0 malformed emails
- 0 orphan appointments
- 0 duplicate resident IDs

Decision:

No additional data-cleaning pipeline is required for these cases. The main
difficulty in this dataset is structural ambiguity rather than malformed
data.

### Harm case

The most important finding is that the contact list can represent one human
through multiple resident records.

Shared emails with identical names, combined with conflicting language and
opt-out information in duplicate-name clusters, mean that counting only
`resident_id` can underestimate how many times one suspected person is
contacted.

Decision:

I will keep the regulator's `resident_id` counting rule separate from any
later identity-protection mechanism. I will not silently merge records.
Potential duplicate humans should be protected by a separate identity guard
rather than by changing the underlying resident records.

### What this means for the design

The data exploration establishes that the reminder system cannot simply:

1. choose the first available contact point,
2. trust the contact type recorded in the CSV,
3. treat `delivered` as proof of reach, or
4. assume every resident record represents a unique human.

These findings will drive channel ordering, outcome grading, contact-point
limits, language selection, and later identity protection.

## 3. Config and Domain Models

### Centralised configuration

All thresholds and runtime configuration for the reminder system are kept in a single frozen `Config` dataclass in `src/config.py`.

This includes:

- simulation start and end times
- tick interval
- project paths
- reminder horizon
- minimum lead time
- quiet hours
- maximum attempts per appointment
- minimum time between attempts
- soft-failure limit for contact points
- daily message limit per contact point
- daily contact limit per resident
- rolling contact limit settings
- identity-guard mode
- channel fallback order
- default language

The purpose is to prevent numeric thresholds and other policy configuration from being scattered throughout the codebase. Future requirement changes should be made through configuration or the appropriate policy rule rather than by searching through unrelated modules.

The configuration is frozen so that it cannot be mutated during a run. If a different configuration is required, a new configuration can be created rather than modifying the active one.

### Domain model boundary

`src/models.py` contains the domain vocabulary used by the rest of the system:

- `Channel`
- `Reach`
- `PointHealth`
- `Resident`
- `Appointment`
- `Decision`
- `Outcome`

The domain models intentionally do not contain reminder-policy or orchestration logic.

Rules such as quiet hours, appointment eligibility, retry limits, rolling contact limits, identity protection, and channel fallback will belong to later modules.

This keeps the domain objects simple and gives policy a single place to enforce contact rules.

### Resident channel mapping

`Resident.point_for()` defines which contact point may be used for each channel:

- SMS uses the `mobile` field only.
- Voice uses `mobile` first and falls back to `landline`.
- Email uses the `email` field.

SMS deliberately does **not** fall back to the landline field.

This decision is important because the supplied data contains numbers in the mobile column that may actually be landlines. Allowing SMS to fall back to the landline column could therefore result in an SMS being sent to a number that cannot receive SMS.

Keeping the mapping inside `Resident.point_for()` also gives later modules one consistent way to obtain the appropriate contact point.

### Resident opt-outs

`Resident.opted_out_of(channel)` only determines whether the resident has opted out of the specified channel.

It does not determine whether the resident may be contacted overall.

The broader decision of whether a contact is permitted belongs to the policy gatekeeper that will be implemented later.

### Reach definition

The system uses four levels of reach evidence:

- `REACHED` — positive evidence that a person engaged.
- `DELIVERED` — the network took the message, but human engagement is unknown.
- `UNVERIFIABLE` — the channel reported success, but there is reason to doubt that the message actually reached a usable recipient.
- `FAILED` — the message did not arrive.

This distinction prevents technical delivery from being treated as proof that a resident was actually reached.

The supplied channel behaviour does not provide a read or reply signal for SMS or email, while a voice call can explicitly report `answered / human`. Therefore, later outcome interpretation must not automatically treat every `delivered` result as `REACHED`.

### Immutability decision

`Config` uses `@dataclass(frozen=True)`.

A mutable configuration could be changed during execution by a future feature or code path, potentially relaxing a threshold without the rest of the system knowing.

Using a frozen configuration makes the active configuration stable for the duration of a run. A different configuration must be represented by a new object.

### What is deliberately not implemented in Chapter 3

The following responsibilities are intentionally left for later chapters:

- channel fallback decisions
- quiet-hour enforcement
- opt-out enforcement at the sending boundary
- appointment eligibility
- retry and stopping rules
- contact-history tracking
- outcome interpretation
- appointment prioritisation
- rolling seven-day contact enforcement
- identity-guard evaluation
- message generation

Chapter 3 establishes the configuration interface and domain vocabulary only.

## 4.  Loading, normalisation, and audit

### Decision: normalise at the loading boundary

All CSV data is normalised when it enters the system. CSV fields are stripped,
emails and language codes are lowercased, opt-out flags are converted from `Y`
to booleans, and appointment timestamps are parsed into `datetime` objects.

This keeps the rest of the system working with canonical domain objects instead
of repeatedly interpreting raw CSV values.

### Decision: derive structural flags once

`suspected_landline_mobile` and `identity_key` are derived during loading rather
than inside policy or the engine.

The suspected-landline flag uses the landline-prefix set observed in the
county data. This identifies 40 mobile numbers. Chapter 2 also identified one
known miss, RS-4431, giving the broader finding of 41 landline-block numbers.
The known miss is not hardcoded into the derived flag because it cannot be
discovered from the observed landline-prefix set. The inference is used as a
signal, not as a reason to suppress contact.

`identity_key` groups records by lowercased email and name and is assigned only
when the group contains more than one resident. Records are not merged because
shared identity clusters can contain contradictory language and opt-out data.

### Decision: audit reference date

Verification staleness is calculated against the configured simulation date,
2026-03-01, rather than the latest appointment date or the system clock.
One-year and two-year boundaries are inclusive.

This produces the Chapter 2 audit results of 382 residents not verified in over
one year and 126 in over two years.

### Chapter 4 verification

`python main.py audit` reproduces the Chapter 2 audit:

- 620 residents
- 940 appointments
- appointment range: 2–31 March 2026
- 14 residents with no contact details
- 11 fully opted out
- 62 without mobile, 407 without landline, 258 without email
- 27 shared mobile numbers / 61 residents
- 69 shared email addresses / 151 residents
- 35 identity clusters disagreeing on language
- 29 identity clusters disagreeing on opt-outs
- 382 not verified in over one year
- 126 not verified in over two years
- 246 non-English appointments
- 215 / 170 / 72 / 36 / 5 residents with 1–5 appointments
- zero malformed phones, malformed emails, orphan appointments, and duplicate IDs

The audit command is intentionally temporary. The full CLI will be introduced
later.

## 5.  Contact Ledger

### Decision: append-only JSONL history

The contact history is stored as JSONL at
`runtime/contact_history.jsonl`.

The ledger records both outbound attempts and withheld-contact decisions.
Records are appended rather than rewritten so the system retains an audit
trail of what it attempted and what policy prevented it from attempting.

### Decision: rolling windows are calculated backwards from the proposed time

The rolling window is defined as:

`start < timestamp <= at`

where `start` is calculated as `at - days`.

I did not use fixed calendar weeks because the requirement is a rolling
seven-day period rather than a week boundary. This also means the system
can demonstrate compliance at an arbitrary proposed contact time.

### Decision: resident_id is the key for resident-level contact counting

`contacts_in_window()` indexes contacts by `resident_id` only.

The contact point, channel, and appointment are deliberately not part of
this key. Therefore:

- SMS and voice attempts count together.
- Different appointments count together.
- A shared contact point does not transfer one resident's contact count
  to another resident.

This follows the requirement that the contact limit applies per resident.
A shared contact point counts only against the resident who was actually
contacted.

A dedicated test verifies that contacting one resident through a shared
contact point does not increase another resident's rolling contact count.

### Decision: failed attempts are contacts

Failed outbound attempts are stored as `attempt` records and are included
in rolling contact counts.

This is intentional because the contact-counting rule defines a contact
as an outbound attempt regardless of whether it was delivered, answered,
or read.

### Decision: withheld records are not contacts

A `withheld` record represents a contact that the system considered but
did not send. It is retained for evidence but does not increase the
resident's contact count because no outbound attempt occurred.

### Decision: indexes are maintained on write

The ledger maintains indexes for:

- resident
- appointment
- contact point
- identity cluster

The indexes are updated when records are loaded or appended. Queries
therefore do not need to scan the complete history file for every policy
check.

This was chosen because the system performs repeated history queries
during a simulation and the project explicitly calls for indexing on
write rather than scanning on read.

### Decision: prior history is imported through the ledger

`import_prior(path)` imports existing JSONL history into the same ledger
and rebuilds the same indexes.

This is required because the later regulatory change applies
retrospectively to contact that occurred before the direction came into
force. The ledger therefore needs to treat prior contact history as part
of the same evidence base.

### Chapter 5 verification

Chapter 5 was verified with the dedicated ledger test suite.

Result:

`10 passed in 0.09s`

The tests cover persistence, rolling-window boundaries, resident-level
counting, shared contact points, cross-channel counting, failed attempts,
withheld records, identity clusters, prior-history import, and write-time
indexes.

## 6.  The gatekeeper

### Decision: centralise all contact permission in `src/policy.py`

All rules determining whether a resident may be contacted are implemented as pure
policy rules in `src/policy.py` and evaluated through the single `RULES` tuple.

The current day-one rules are:

1. appointment relevance
2. already reached
3. channel opt-out
4. contact-point existence
5. known-bad contact point
6. quiet hours
7. appointment attempt cap
8. duplicate-message/shared-point protection
9. resident daily cap

The first rule that objects blocks the contact. If no rule objects, the decision
is allowed.

This gives the system one obvious place for future contact rules. A new rule is
added as another policy function and placed in `RULES`, rather than being
scattered across the engine or channel call sites.

### Decision: make authorization unbypassable

A successful policy evaluation does not itself send anything.
`policy.authorize()` issues an immutable `Authorization` object containing the
exact resident, appointment, channel, contact point, timestamp and attempt
number.

The authorization contains a module-private mint that callers cannot reproduce.
`dispatch.send()` verifies the authorization before touching the supplied
channel.

This was chosen because a policy check at a call site can be forgotten by a
future feature. The authorization boundary makes that mistake fail instead of
silently bypassing policy.

An authorization for one recipient, channel or timestamp cannot be reused for
another send.

### Decision: enforce quiet hours and opt-outs in policy

Quiet hours are enforced from 21:00 to 08:00, and channel-specific opt-outs block
only the opted-out channel.

These protections live in the gatekeeper rather than in the engine because the
supplied messaging channels enforce nothing themselves. A future caller
therefore cannot simply bypass them by calling the channel through the normal
dispatch path.

### Decision: protect shared contact points separately from residents

A contact point has its own daily message cap. This is separate from the resident
daily cap.

The reason is that two residents may legitimately share a phone number. They
remain separate residents and are not merged, but the person holding the phone
should not receive an unrestricted stream of messages simply because different
resident IDs are associated with the same point.

Identical message bodies are also blocked on a shared point, except when the
identical message is a retry for the same appointment after a failed attempt.

### Decision: use conservative stopping rules

The day-one stopping rules include a maximum of three attempts per appointment,
a minimum of 18 hours between attempts, dead-point protection, soft-failure
limits, shared-point daily limits and resident daily limits.

The system therefore does not continue retrying indefinitely when a contact
point repeatedly fails.

The adaptive stopping rule from the "if you have time" section was not
implemented in this chapter because the floor requirements were prioritised
first.

### What this chapter does not do

Chapter 6 does not implement language templates, the reminder engine, metrics,
the CLI, or the day-two rolling contact limit and identity guard.

The rolling contact limit and identity guard are deliberately left for the later
Direction CR-2026/11 change rather than being implemented early.

## 7.  Templates and language

### Per-resident template selection

Message templates are selected from the resident's recorded `language` rather than using one template for everyone.

The system ships templates for `en`, `es`, and `vi`.

A `Message` records both `requested_language` and the actual `language` used. This preserves the difference between a resident who requested English and a resident whose requested language was unavailable.

Examples:

- `es` resident → `es` template, `fallback=False`
- `so` resident → `en` template, `fallback=True`

### Language fallback

The system falls back to English when a resident's requested language has no template.

The fallback is explicit rather than silent. `Message.fallback` is set to `True`, while `requested_language` retains the resident's original language and `language` records `en`.

This makes fallback measurable and allows the system to report how many messages were sent using a language different from the resident's preference.

### Deliberately missing templates

I deliberately did not create `ru.json`, `so.json`, or `zh.json`.

Creating placeholder files for every language would make those languages appear supported and would prevent the fallback path from being exercised. The problem specifically requires fallback to be observable rather than silently hiding how many residents received a message in a different language.

The non-English templates are clearly marked as placeholders because the problem pack says real translations are not expected and cannot be meaningfully checked.

### Message hashing

The final rendered message exposes a `body_hash` property using SHA-256.

The hash is calculated from the rendered message body rather than the template itself. This allows the existing policy layer to detect duplicate message bodies sent to the same contact point without making the policy responsible for template rendering.

### What I rejected

I rejected:

- Shipping placeholder templates for `ru`, `so`, and `zh`.
- Treating English as the requested language when a resident actually requested another language.
- Using an external translation service or LLM to generate translations.
- Putting language-selection logic inside the policy or dispatch layers.

Language selection belongs in the message-building layer so policy remains responsible for contact permission and dispatch remains responsible for channel delivery.

## 8.  Dispatch and outcome grading

### Decision

I kept channel integration isolated in `src/dispatch.py`. This is the only
production module that imports the supplied `channels` infrastructure.

Authorization is verified before any channel is touched, so dispatch cannot
send without a valid policy-issued `Authorization`.

I set `OUTBOX_PATH` before importing and reloading the supplied channels module.
This ensures channel output is written to the configured runtime directory
instead of depending on the directory from which the program was launched.

I deliberately left `channels/channels.py` unchanged because it is supplied
infrastructure and its behaviour is part of the problem.

### Outcome interpretation

I grade carrier results more conservatively than the carrier reports them.

`delivered` is not treated as `REACHED` because SMS and email provide no
evidence that a person actually read or engaged with the message.

The only result treated as `REACHED` is:

`voice / answered / human`

The `delivered / accepted_by_carrier` SMS result is treated as
`UNVERIFIABLE` with `WRONG_CHANNEL` because it indicates the message was
accepted by the carrier even though the destination cannot receive SMS.

Unknown carrier outcomes are deliberately treated as
`UNVERIFIABLE` with `SOFT` point health rather than being assumed successful.

### What this does not do

Dispatch does not make policy decisions about opt-outs, quiet hours,
deduplication, attempt limits, or contact frequency. Those rules belong in the
policy gatekeeper. Dispatch only verifies the authorization, performs the
authorized send, and interprets the carrier result.

## 9.  Engine Orchestration

### Decision

Replaced the engine with an orchestration-only implementation.

The engine is responsible for:
- Selecting appointments that are currently relevant.
- Prioritising appointments using previous attempt count, appointment time, and appointment ID as a deterministic tie-breaker.
- Selecting the channel order.
- Building the appropriate message.
- Asking policy for permission before every contact.
- Dispatching only after policy issues an authorization.
- Recording attempts and withheld appointments.
- Running deterministic ticks through `simulate()`.

The engine does not contain permission rules. Quiet hours, opt-outs, contact limits, duplicate protection, contact-point health, and future regulatory restrictions remain policy responsibilities.

### One contact per appointment per tick

A single appointment can produce at most one outbound attempt during a tick.

If the first channel fails, the engine does not immediately try another channel. The next channel can only be considered on a later tick.

This prevents channel fallback from becoming repeated contact within one batch.

### Prioritisation

Appointments are processed using two levels:

1. Appointments with fewer previous attempts are prioritised.
2. Earlier appointments are prioritised within the same attempt count.

Appointment ID is used only as a deterministic tie-breaker.

No protected characteristic is used for prioritisation.

### Withheld appointments

When policy blocks every available channel, the engine records the appointment as withheld.

The withheld record contains the primary policy reason and the channel-level blocking decisions so that a later audit can explain why the appointment was not contacted.

### Day-two requirement

The rolling seven-day contact limit and identity guard remain policy concerns rather than engine rules.

This keeps the engine compatible with future changes to who may be contacted, how often, or through which channel without creating a second permission system.

### Known limitation

The current policy implementation must provide the Chapter 13 rolling-limit and identity-guard decisions before those rules can actually prevent contact. The engine deliberately does not duplicate those rules.

## 10.   Metrics and Reporting

### Decision

Implemented a dedicated metrics layer in `src/metrics.py` rather than
putting reporting logic inside the engine or policy modules.

The system reports three headline measures:

1. **Confirmed reach rate**
   - An appointment counts as reached only when there is positive
     `REACHED` evidence.
   - A carrier `delivered` result is not treated as confirmed reach.

2. **Coverage gap**
   - Counts appointments that received no outbound contact.
   - The report groups these appointments by the recorded withholding
     reason so the system can show why coverage was missed.

3. **Harm ceiling**
   - Reports the maximum number of contacts made to one resident within
     any rolling seven-day window.
   - Also reports the maximum contact count for an `identity_key` where
     multiple resident records appear to represent the same person.

### Rolling-window compliance

The metrics layer independently recomputes contact counts for every
recorded attempt.

This is intentionally separate from the policy implementation so that
the compliance report provides an independent check of the two-contact
rolling seven-day requirement rather than simply calling the same policy
rule that authorised the send.

Failed outbound attempts are counted as contacts because the regulator's
direction defines a contact as any outbound attempt, regardless of
whether it was delivered or answered.

### Silent failures

Carrier responses that look successful but provide unreliable evidence
are reported separately as silent-failure exposure.

Examples include:

- SMS accepted by a carrier for a suspected landline.
- Email reported as delivered but placed in spam.

These are not counted as confirmed human reach.

### Language fallback

Language fallback is reported separately so that residents whose
preferred language has no supplied template are visible in the metrics.

The system continues to use the configured English fallback, but the
fallback is recorded rather than being silent.

### What was deliberately not used as the primary metric

"Messages sent" is not treated as a measure of success.

A high number of outbound messages can mean that the system is contacting
people repeatedly without actually reaching them. The primary metric is
therefore confirmed reach, with coverage gap and harm ceiling reported
alongside it.

### Scope

The metrics layer does not make contact decisions.

It only measures recorded attempts, outcomes, withheld appointments,
language fallback, and rolling-limit compliance. Permission and
authorisation remain the responsibility of the policy layer.

## 11.  CLI

### Decision: keep the CLI as a thin orchestration layer

The CLI exposes five commands: `audit`, `run`, `report`, `explain`, and `trace`.
The CLI does not contain reminder policy, channel rules, or metric calculations.
It parses arguments and connects the existing loader, ledger, engine, policy,
dispatch, and metrics components.

### Deterministic execution

`run` requires explicit `--now` and `--until` values. Batch execution is driven
by explicit tick hours rather than the system clock. This makes a run reproducible
and makes quiet-hour behaviour demonstrable.

### Retrospective history

`--seed-history` imports contact records before the simulation begins. This is
necessary because Direction CR-2026/11 applies retrospectively to contact already
made.

### Fresh runs

`--fresh` removes the stored contact history and outbox before starting. This
prevents previous executions from contaminating a demonstration or comparison.

### Evidence commands

`explain` was treated as a first-class debugging and compliance command rather
than a reporting convenience. It exposes the preceding seven days of contacts
and withheld decisions for a resident, directly supporting Direction s.5.1.

`trace` exposes the stored history for one appointment so an individual reminder
can be followed from attempt through outcome or withholding.

### What I deliberately did not add

I did not add a CLI framework, database, API, or user interface. The problem
accepts command-line delivery and interface quality is not assessed. The goal
was to expose the evidence already produced by the system without creating a
second layer of business logic.

### Trade-off

The CLI owns parsing of `--tick-hours 4,9` because this represents explicit daily
batch times. The engine's existing simulation interval is not overloaded with
CLI-specific syntax.