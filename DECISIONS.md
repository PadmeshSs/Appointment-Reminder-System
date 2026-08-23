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