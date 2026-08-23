# AI-USAGE.md

# Brite Spark 2026 — Problem 7
## AI Usage Log

AI assistance was used during the development of Problem 7 — The Reminder That Reaches.

AI was used as a development and reasoning aid for understanding requirements, planning the repository structure, interpreting the supplied data, explaining implementation decisions, reviewing code structure, and identifying potential edge cases.

The author remains responsible for understanding, testing, modifying, and defending every line of the final repository.

---

# Chapter 1 — Repository and Git Discipline

## AI assistance used for

AI was used to:

- interpret the Brite Spark repository and submission requirements;
- explain the purpose of the required repository structure;
- plan the initial project skeleton;
- explain Git branches and the purpose of a development branch;
- explain how chapter-specific branches should be created;
- explain how changes should move from a chapter branch into `development`;
- explain how `main`, `development`, and chapter branches relate to each other;
- explain Git commands used during repository setup;
- explain the purpose of meaningful commits throughout the project;
- help establish a commit-message convention;
- clarify why the project should not be submitted as one large commit;
- review the purpose of `DECISIONS.md`;
- explain why `AI-USAGE.md` is required by the competition.

## Repository workflow

The project was structured around chapter-based development.

The intended workflow is:

1. Work on a chapter-specific branch.
2. Implement and verify that chapter.
3. Commit the completed work.
4. Merge the chapter branch into `development`.
5. Continue the next chapter from the updated `development` branch.
6. Keep `main` as the stable submission branch.

This approach was chosen to preserve the real commit history required by the Brite Spark judging criteria.

## AI role

AI was primarily used to explain Git concepts and help reason about the development workflow.

The actual repository, branches, commits, and Git operations were performed and verified by the author.

---

# Chapter 2 — Data Exploration and Representation

## AI assistance used for

AI was used to:

- break the data-exploration requirements into concrete questions;
- suggest exploratory scripts for examining the supplied CSV files;
- explain how to inspect the contact and appointment data before designing the system;
- explain Python path handling used by exploration scripts;
- help interpret the structure of the supplied data;
- reason about anomalies and unusual contact-point relationships;
- distinguish data exploration from production data-cleaning logic;
- explain why assumptions about the dataset should not be invented without evidence;
- interpret the implications of shared contact points, opt-outs, languages, missing contact details, and stale verification dates.

## Data findings used in the design

The supplied data was inspected before the production architecture was designed.

Important findings included:

- 620 residents;
- 940 appointments;
- appointments actually extend through 31 March 2026 even though the pack README describes the range as 2–29 March;
- 14 residents have no contact details at all;
- 11 residents are opted out of all three channels;
- 41 numbers in the mobile column appear to be landlines based on evidence from the supplied data;
- 27 mobile numbers are shared by multiple residents;
- 69 email addresses are shared by multiple residents;
- the shared-email records have identical names;
- duplicate-name clusters can disagree on language;
- duplicate-name clusters can disagree on opt-outs;
- contact details have varying verification ages.

These findings were used to influence later design decisions rather than assuming that the data was clean.

## Important reasoning

AI assistance was used to reason about the consequences of the observed data rather than automatically "cleaning" it.

In particular, the shared-contact-point problem was treated as a system-design issue rather than simply deleting or merging records.

The landline issue was also treated cautiously. The project guidance explicitly warns against reading the secret landline rule from the mock channel implementation and hardcoding it into the application.

## AI role

AI helped formulate exploration questions and interpret findings.

The actual dataset was inspected by the author, and design decisions are based on the supplied data and project documents.

---

# Chapter 3 — Config and Domain Models

## AI assistance used for

AI was used to:

- break the Chapter 3 specification into implementation steps;
- explain why configuration should be centralised;
- explain the purpose of an immutable/frozen configuration object;
- identify the configuration fields required by the project;
- explain the responsibilities of the domain models;
- structure the `Channel`, `Reach`, `PointHealth`, `Resident`, `Appointment`, `Decision`, and `Outcome` types;
- review the `Resident.opted_out_of()` behaviour;
- review the `Resident.point_for()` channel mapping;
- explain why SMS must never use the `landline` column;
- clarify the distinction between `REACHED`, `DELIVERED`, `UNVERIFIABLE`, and `FAILED`;
- identify which logic should remain outside the domain models and be implemented later in policy, dispatch, history, and engine modules.

## Configuration design

AI assistance was used to reason about keeping thresholds in a single frozen `Config` dataclass.

The configuration contains values relating to:

- simulation time;
- tick frequency;
- paths;
- reminder timing;
- quiet hours;
- attempt limits;
- contact-point failure limits;
- shared contact-point limits;
- resident contact limits;
- rolling contact limits;
- identity-guard behaviour;
- channel fallback;
- language fallback.

The purpose is to prevent thresholds from being scattered throughout the codebase and to provide a clear location for future requirement changes.

## Domain model boundary

AI assistance was used to establish the boundary between domain objects and policy.

The domain models define what the system's entities are, while later modules will determine:

- whether a contact is permitted;
- when a reminder is due;
- which channel should be attempted;
- when retries stop;
- how contact history affects a decision;
- how outcomes affect contact-point health.

This prevents reminder policy from being embedded inside `Resident` or other domain objects.

## Resident contact-point rule

AI assistance was used to review the required contact-point behaviour:

- SMS → mobile only;
- Voice → mobile, falling back to landline;
- Email → email.

The important rule is that SMS never uses the landline column.

## Reach definition

AI assistance was used to clarify the four-level reach model:

- `REACHED` — positive evidence that a person engaged;
- `DELIVERED` — the network took the message, but human engagement is unknown;
- `UNVERIFIABLE` — reported success that has reason to be doubted;
- `FAILED` — the message did not arrive.

This prevents technical delivery from being incorrectly treated as proof that a resident was reached.

## AI role

AI was used for explanation, decomposition, design review, and implementation assistance.

The implementation remains the author's responsibility and must be understood and explainable before submission.

---

# AI Errors, Corrections, and Verification

This section will be maintained throughout the project.

The purpose is to record cases where an AI suggestion conflicts with:

- the supplied problem document;
- the supplied data;
- the supplied channel behaviour;
- the regulator's direction;
- tests;
- or another piece of project evidence.

No specific AI-generated error is being recorded here unless it was actually encountered and verified.

The project will not claim an AI mistake merely for the sake of filling this section.

---

# Responsibility

AI assistance does not replace responsibility for the final repository.

The author is responsible for:

- understanding the implementation;
- verifying behaviour against the supplied data;
- testing the system;
- making final architectural decisions;
- documenting trade-offs;
- explaining the code during judging;
- identifying and correcting errors in AI-generated suggestions.

Before submission, this document will be updated to include the actual AI assistance used during the remaining chapters, including implementation, debugging, testing, documentation, and any verified AI mistakes that were caught.

## Chapter 4

AI was used to help:

- structure `src/loading.py`;
- implement CSV loading with `utf-8-sig`;
- implement field normalisation;
- implement datetime parsing;
- implement the derived `identity_key` and
  `suspected_landline_mobile` logic;
- structure the `audit()` function;
- create the temporary `main.py audit` command;
- debug discrepancies between the audit output and the Chapter 2 findings.

## Errors caught and corrected

AI initially used the latest appointment date as the reference date for
verification staleness. This produced 400 residents over one year and 141 over
two years instead of the required 382 and 126.

The error was identified by comparing the implementation against the Chapter 2
audit. The calculation was corrected to use the configured simulation date of
2026-03-01 with inclusive one-year and two-year boundaries.

AI also initially treated the 41 landline-block numbers as though all 41 could
be derived from the observed landline-prefix set. The Chapter 2 analysis shows
that only 40 are inferred from the observed prefixes and that RS-4431 is a
known miss. The loader therefore retains the observed-prefix inference rather
than hardcoding the exception.

All AI-generated code was reviewed, tested, and modified as necessary. The
implementation is my responsibility and I can explain its behaviour and
design decisions.

## Chapter 5 — Contact Ledger

### AI assistance used

AI assistance was used during Chapter 5 to:

- break the chapter specification into implementation tasks;
- explain the distinction between an append-only evidence ledger and
  policy logic;
- explain the rolling-window boundary:
  `start < timestamp <= at`;
- explain why resident-level contact counting must be keyed by
  `resident_id`;
- identify the need for separate resident, appointment, contact-point,
  and identity indexes;
- generate an initial implementation of `src/history.py`;
- generate focused tests for the Chapter 5 requirements;
- help diagnose the missing `pytest` dependency when the test command
  initially failed.

### Human verification

The generated implementation was tested locally using:

`python -m pytest tests/test_history.py -v`

The Chapter 5 test suite completed with:

`10 passed in 0.09s`

The tests specifically verified the resident-key decision, shared contact
point behaviour, rolling-window boundary, persistence after reload, failed
attempt counting, withheld records, identity-cluster queries, prior
history import, and write-time indexes.

The implementation was reviewed against the Chapter 5 specification and
the contact-counting requirements before considering the chapter complete.

### AI-generated code

AI generated an initial version of the Chapter 5 ledger implementation
and its focused tests. The code was not accepted solely on generation;
it was executed and verified locally, and the resulting test failures
would have been investigated before committing.

### Human responsibility

The final design decisions, review of the requirements, acceptance of the
implementation, and decision to commit the Chapter 5 work remain the
developer's responsibility.

## Chapter 6 — The gatekeeper

### AI used

I used ChatGPT to help structure and implement the Chapter 6 policy gatekeeper,
including:

- designing the `Authorization` object and private authorization mint
- structuring the policy rules as pure functions
- implementing the ordered `RULES` pipeline
- implementing the `dispatch.send()` authorization boundary
- generating initial tests for opt-outs, quiet hours, stopping rules, duplicate
  messages and authorization misuse
- reviewing the implementation against the Chapter 6 requirements

I reviewed the generated code and ran the tests locally rather than treating the
generated implementation as automatically correct.

### What I verified

The Chapter 6 policy tests cover:

- channel-specific opt-outs
- quiet hours at 04:00 and release at 09:00
- passed and out-of-window appointments
- missing contact points
- appointment attempt limits
- minimum time between attempts
- dead and repeatedly failing contact points
- already-reached appointments
- shared contact-point daily limits
- duplicate message protection
- legitimate failed retries
- forged authorizations
- authorization reuse against another recipient
- authorization reuse against another channel
- authorization reuse at another timestamp

The resulting test run passed:

`21 passed`

### Important design point

The key architectural requirement was not simply to check policy before sending.
The implementation makes `Authorization` the permission boundary.

`policy.authorize()` is the only place that can mint a valid authorization, while
`dispatch.send()` verifies that authorization before touching a messaging
channel.

This means a future code path that forgets to call policy cannot silently send
through dispatch with a forged or missing authorization.

### AI limitations / corrections

I did not treat generated code as authoritative. The implementation was checked
against the project Bible and the supplied problem requirements, then verified
through tests.

The day-two Direction CR-2026/11 rules were deliberately kept out of Chapter 6.
Those rules belong to the later retro-fit chapter and should be added to the
same policy pipeline when the requirement change arrives.

## Chapter 7 — Templates and language

### AI used

I used ChatGPT to help design and implement the Chapter 7 message-template system.

AI assistance was used for:

- Structuring the `Message` model.
- Implementing per-resident template selection.
- Implementing English fallback when a requested language template is missing.
- Implementing the `body_hash` property.
- Generating tests for language selection, fallback behaviour, placeholders, and hashing.
- Reviewing the separation between message generation, policy, and dispatch.

### Decisions I made

I chose to ship only `en.json`, `es.json`, and `vi.json`.

I intentionally did not create `ru.json`, `so.json`, or `zh.json` because the missing templates keep the fallback path live and measurable.

I also chose to store both `requested_language` and the actual `language` used. This makes a fallback distinguishable from a resident who actually requested English.

### Verification

I verified the implementation with tests covering:

- English selecting the English template.
- Spanish selecting the Spanish template.
- Vietnamese selecting the Vietnamese template.
- Somali falling back to English with `fallback=True`.
- Russian and Chinese falling back to English.
- Required placeholders being rendered.
- Stable message hashes.
- Different rendered messages producing different hashes.
- Only the intended template files being present.

The non-English template copy is explicitly marked as placeholder content because the problem pack states that real translations are not expected to be produced or checked.

I am responsible for understanding and being able to explain the code committed to the repository.

## Chapter 8 — AI usage

AI was used to help structure and review the dispatch implementation and to
generate the initial outcome-interpretation tests.

I reviewed the implementation against the Chapter 8 requirements and retained
the conservative interpretation rules:

- `delivered` is not `REACHED`.
- `voice / answered / human` is the only positive reach evidence.
- `accepted_by_carrier` is treated as `UNVERIFIABLE` and `WRONG_CHANNEL`.
- Unknown carrier outcomes are not treated optimistically.

AI also helped identify the importance of setting `OUTBOX_PATH` before
importing and reloading the supplied `channels` module.

I remain responsible for the implementation and can explain why each outcome
is classified the way it is.