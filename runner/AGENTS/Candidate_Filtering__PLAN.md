# Candidate Filtering Plan

> **Goal**: Revisit how the candidate set is determined before entropy
> measurement, so that |Ωᵢ| reflects genuine semantic ambiguity rather than
> an arbitrary threshold.

---

## Current State

`om-batch-search` retrieves `top-k` candidates (default 25) per concept via
vector similarity search, then filters by `min_score_ratio` (default 0.75) —
candidates scoring below 75% of the top score are dropped. The filtered
count is what the LLM sees in its evaluation prompt.

## Known Limitation

The filtering threshold is relative to the top score, not absolute. Two
concepts with the same number of genuinely plausible alternatives can get
very different candidate counts depending on how strong the top match is:

- Strong top match (0.95): keeps candidates down to score 0.71
- Weak top match (0.50): keeps candidates down to score 0.375

This means entropy values (log₂ of candidate count) are influenced by the
embedding model's score distribution as much as by genuine semantic
ambiguity. The entropy measures ambiguity *as presented to the LLM*, which
is useful but not the same as true boundary uncertainty.

## Investigation Path

1. **Empirical analysis**: After a run with provenance (Item 4), compare
   candidate counts to which candidates the LLM actually referenced in its
   rationale. How many candidates does the LLM meaningfully consider?

2. **Score distribution analysis**: Across completed runs, plot the score
   distribution per concept. Is there a natural gap between "plausible" and
   "noise" candidates, or is it a smooth curve?

3. **Absolute threshold**: Would an absolute score floor (e.g., 0.5) produce
   more stable entropy values than a relative ratio?

4. **Adaptive filtering**: Could the threshold be concept-specific, based on
   the score distribution shape (e.g., elbow detection)?

## Dependencies

- Item 3 (Pre-Rotation Entropy) — provides the entropy values to evaluate
- Item 4 (Rotation Provenance) — provides evidence of which candidates the
  LLM actually used
- Completed pipeline runs — empirical data needed

## Status

Not started. Noted as a known limitation during Item 3 planning
(2026-04-09). Revisit after Items 3 and 4 are implemented and empirical
data is available.
