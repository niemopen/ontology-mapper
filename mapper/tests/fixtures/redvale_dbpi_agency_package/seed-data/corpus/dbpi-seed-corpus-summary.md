# DBPI Realistic Seed Corpus

This corpus extends the baseline seed data with a more operationally realistic set of fictional municipal records.

## Included scenarios

1. **Permit completed successfully**
   - electrical panel upgrade at 18 Harbor Avenue
   - approved review, issued permit, final inspection pass, permit finaled

2. **Enforcement case escalated to hearing**
   - unpermitted garage conversion at 77 Juniper Lane
   - complaint intake, field observation, notice of violation, corrective action, appeal denied, administrative hearing

3. **Public records request**
   - request for property history at 500 Market Street
   - request document, response document, records-unit assignment

## Files
- `seed-data/corpus/dbpi-seed-corpus.ttl`
- `seed-data/corpus/dbpi-seed-corpus-summary.md`

## Modeling notes

- The corpus remains fictional.
- It is written to look like actual departmental operational records.
- Records request artifacts are represented through `Document` and `PublicService` because the base ontology does not yet define a dedicated `RecordsRequest` class.
