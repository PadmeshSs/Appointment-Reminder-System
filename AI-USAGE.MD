# AI Usage

## Overview

AI was used as an implementation, debugging, review, and documentation
assistant throughout the project.

The problem document, supplied data, repository behaviour, tests, and measured
CLI results remained the authority.

AI suggestions were reviewed against the actual files and executed locally
before being treated as part of the implementation.

## What AI was used for

AI assistance was used for:

- repository and architecture review;
- data-edge-case analysis;
- policy-rule design;
- test design;
- implementation of policy and ledger behaviour;
- debugging failing tests;
- retrospective-history fixture generation;
- identity-guard design;
- metrics and compliance reasoning;
- CLI and deterministic-run design;
- README and decision-document drafting;
- demo-script structure.

## Where AI was wrong

AI made several incorrect assumptions during the build. These were caught by
checking the supplied data, repository, or actual execution.

### 1. `resident_id` means different people

AI initially treated different `resident_id` values as sufficient evidence that
two records represented different people.

That was false.

The contact list contains shared identity clusters, including shared email
addresses with identical names. Some of those clusters also contain
contradictory language or opt-out information.

The correction was to keep the regulator's resident-level counter unchanged
while adding a separate suspected-identity guard.

### 2. The appointment pack covered 2–29 March

AI initially repeated the stated pack range without checking the actual CSV.

The data contains appointments through **31 March 2026**.

The correction was to treat the supplied CSV as authoritative and use
2–31 March in the audit and March simulation.

### 3. Fallback could send three channels in one run

An early fallback design risked treating channel fallback as permission to try
multiple channels during the same tick.

That would have created repeated contact within one batch.

The correction was to enforce one outbound attempt per appointment per tick. If
the first channel fails, another channel can only be considered on a later tick
after policy is evaluated again.

### 4. Carrier delivery could be treated as reach

AI initially risked treating a technical `delivered` result as successful
human contact.

The supplied channel behaviour does not establish that a person read or
engaged with an SMS or email.

The correction was to grade only `voice / answered / human` as `REACHED`.
Carrier delivery without human evidence is not confirmed reach.

### 5. Retrospective history could be generated through shell redirection

The initial fixture-generation approach used shell redirection:

```text
python tools/make_prior_contacts.py > runtime/prior_contacts.jsonl