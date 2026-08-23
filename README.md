# Appointment Reminder System

A deterministic appointment-reminder system that decides whether, when, and
through which channel a resident should be contacted while respecting
opt-outs, quiet hours, contactability, retry limits, rolling contact limits,
and suspected duplicate-person protection.

## Clone and run

```bash
git clone https://github.com/PadmeshSs/Appointment-Reminder-System.git
cd Appointment-Reminder-System

python -m pytest tests -q
./demo.sh
```

The demo runs the audit, retrospective-history import, compliant March run,
resident-level explanation, counterfactual run without the Direction, restores
the compliant state, and runs the full test suite.

On Windows, run the individual commands from `demo.sh` with `python3` instead
of `python`, or use Git Bash.

## Success definition

| Measure | Definition | Final verified result |
|---|---|---|
| Confirmed reach rate | Appointments with at least one REACHED event | 25.4% |
| Coverage gap | Appointments receiving no outbound contact | 142 |
| Harm ceiling — resident | Maximum contacts to one resident in any rolling 7-day window | 2 |
| Harm ceiling — suspected person | Maximum contacts to one suspected identity in any rolling 7-day window | 2 |
| Direction compliance | Independent rolling-window compliance check | 0 breaches |

> `delivered` is not confirmed human reach. The only outcome graded as
> `REACHED` is a voice call answered by a human.

## Verified March results

The final compliant run used:

- Start: `2026-03-01 09:00`
- Until: `2026-03-31 09:00`
- Ticks: 61
- Attempts: 1,275
- Withheld: 3,647
- Rolling limit: enabled
- Identity guard: enforce

| Run | Confirmed reach | Coverage gap | Resident max | Person max |
|---|---|---|---|---|
| Baseline: no Direction, guard off | 41.0% | 34 | 6 | 9 |
| Direction, guard off | 26.1% | 125 | 2 | 6 |
| Direction + identity guard | 25.4% | 142 | 2 | 2 |

The final compliant run reported:

```
Compliance breaches: 0
Status: COMPLIANT
```

The identity guard reduced the worst observed suspected-person contact count
from 6 to 2.

## Architecture

```
                 +----------------------+
                 |       contacts.csv   |
                 |    appointments.csv  |
                 +----------+-----------+
                            |
                            v
                    +---------------+
                    |   loading.py  |
                    | normalisation |
                    +-------+-------+
                            |
                            v
                    +---------------+
                    |    models.py  |
                    | domain model  |
                    +-------+-------+
                            |
             +--------------+--------------+
             |                             |
             v                             v
      +-------------+               +-------------+
      |  policy.py  |<--------------|  history.py |
      | gatekeeper  |               | append-only |
      +------+------+               | JSONL ledger|
             |                      +-------------+
             | authorization
             v
      +-------------+
      | dispatch.py |
      | channel I/O |
      +------+------+
             |
             v
      +-------------+
      |  channels   |
      | supplied    |
      +-------------+

             ^
             |
      +------+------+
      |  engine.py  |
      | orchestration|
      +------+------+
             ^
             |
      +------+------+
      |   main.py   |
      |    CLI      |
      +------+------+
             |
             v
      +-------------+
      | metrics.py  |
      | reporting   |
      +-------------+
```

The engine orchestrates the workflow but does not decide whether a contact is
permitted. Policy is the single contact-permission gate. The ledger records
attempts and withheld decisions. Dispatch cannot send without a policy-issued
authorization.

## Module responsibilities

| Module | Responsibility |
|---|---|
| `src/models.py` | Domain vocabulary: residents, appointments, channels, outcomes, decisions |
| `src/config.py` | Immutable runtime and policy configuration |
| `src/loading.py` | CSV loading, normalisation, suspected-landline and identity derivation |
| `src/history.py` | Append-only contact ledger, rolling-window queries, prior-history import and indexes |
| `src/policy.py` | All contact-permission rules and authorization |
| `src/message.py` | Language selection, fallback and message hashing |
| `src/dispatch.py` | Authorization verification, channel dispatch and outcome grading |
| `src/engine.py` | Appointment prioritisation, channel ordering, orchestration and recording |
| `src/metrics.py` | Reach, coverage, harm ceiling and independent compliance reporting |
| `main.py` | Thin CLI orchestration |
| `tools/make_prior_contacts.py` | Deterministic retrospective history fixture |
| `demo.sh` | Six-section judge demonstration |

## Direction CR-2026/11 — clause to code

| Direction clause | Implementation |
|---|---|
| s.1 — maximum two contacts in rolling seven days | `policy._rule_rolling_limit()` |
| s.2.1 — failed attempts still count | `history.py` stores failed outbound attempts as contacts |
| s.2.2 — limit applies across channels | `Ledger.contacts_in_window()` is keyed by `resident_id` |
| s.2.3 — shared point counts against one resident | Resident-level history index |
| s.2.4 — rolling window | `Ledger.contacts_in_window()` uses `start < timestamp <= at` |
| s.3.1 — prior contact | `Ledger.import_prior()` + `--seed-history` |
| s.3.1 — retrospective evidence | `tools/make_prior_contacts.py` |
| s.5.1 — explain decision | `main.py explain` |
| Identity protection | `policy._rule_identity_guard()` |
| Independent compliance proof | `metrics.py` rolling-window verification |

## Running individual commands

Audit the supplied data:

```bash
python main.py audit
```

Run the compliant March simulation:

```bash
python main.py run \
  --fresh \
  --seed-history runtime/prior_contacts.jsonl \
  --now "2026-03-01 09:00" \
  --until "2026-03-31 09:00" \
  --tick-hours 4,9 \
  --identity-guard enforce
```

Generate retrospective history:

```bash
python tools/make_prior_contacts.py \
  --output runtime/prior_contacts.jsonl
```

Explain one resident's rolling contact history:

```bash
python main.py explain \
  --resident RS-4000 \
  --date "2026-03-02 09:00"
```

Run the complete test suite:

```bash
python -m pytest tests -q
```