#!/usr/bin/env bash

set -euo pipefail
cd "$(dirname "$0")"

mkdir -p runtime

NOW="2026-03-01 09:00"
UNTIL="2026-03-31 09:00"
TICKS="4,9"
RESIDENT="RS-4000"
EXPLAIN_DATE="2026-03-02 09:00"
HISTORY="runtime/prior_contacts.jsonl"

echo "============================================================"
echo "1. AUDIT — what is actually in the contact list"
echo "============================================================"

python3 main.py audit > runtime/demo_audit.txt
head -80 runtime/demo_audit.txt

echo
echo "============================================================"
echo "2. RETROSPECTIVE CONTACT HISTORY — Direction s.3.1"
echo "============================================================"

python3 tools/make_prior_contacts.py \
  --output "$HISTORY"

echo "Generated prior-contact history:"
wc -l "$HISTORY"

echo
echo "============================================================"
echo "3. COMPLIANT MONTH — Direction in force"
echo "============================================================"

python3 main.py run \
  --fresh \
  --seed-history "$HISTORY" \
  --now "$NOW" \
  --until "$UNTIL" \
  --tick-hours "$TICKS" \
  --identity-guard enforce \
  > runtime/demo_compliant_run.txt

head -40 runtime/demo_compliant_run.txt

python3 main.py report \
  --now "$NOW" \
  --until "$UNTIL" \
  > runtime/demo_compliant_report.txt

head -80 runtime/demo_compliant_report.txt

echo
echo "============================================================"
echo "4. EXPLAIN — one resident, one date"
echo "============================================================"

python3 main.py explain \
  --resident "$RESIDENT" \
  --date "$EXPLAIN_DATE" \
  > runtime/demo_explain.txt

head -100 runtime/demo_explain.txt

echo
echo "============================================================"
echo "5. COUNTERFACTUAL — no Direction, no identity guard"
echo "============================================================"

python3 main.py run \
  --fresh \
  --now "$NOW" \
  --until "$UNTIL" \
  --tick-hours "$TICKS" \
  --no-limit \
  --identity-guard off \
  > runtime/demo_no_limit_run.txt

head -40 runtime/demo_no_limit_run.txt

python3 main.py report \
  --now "$NOW" \
  --until "$UNTIL" \
  > runtime/demo_no_limit_report.txt

head -80 runtime/demo_no_limit_report.txt

echo
echo "============================================================"
echo "6. RESTORE COMPLIANT RUN + TESTS"
echo "============================================================"

python3 main.py run \
  --fresh \
  --seed-history "$HISTORY" \
  --now "$NOW" \
  --until "$UNTIL" \
  --tick-hours "$TICKS" \
  --identity-guard enforce \
  > runtime/demo_final_run.txt

head -40 runtime/demo_final_run.txt

python3 main.py report \
  --now "$NOW" \
  --until "$UNTIL" \
  > runtime/demo_final_report.txt

head -80 runtime/demo_final_report.txt

python3 -m pytest tests -q