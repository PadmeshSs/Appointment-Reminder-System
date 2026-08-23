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