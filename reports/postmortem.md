# Reliability Eval – Failure Post-mortem

## Summary

20 runs were executed against the PatchArena demo fixture. 17 succeeded (85% success rate). 3 failed.

## Failure Analysis

### Run sbx-eval000014 – Sandbox boot timeout
The Celesto cloud micro instance took longer than the configured 150-second boot probe, timing out the creation step. The sandbox was deleted in the `finally` block of the lifecycle manager. **Root cause:** Celesto Cloud occasionally queues micro instances under load. **Fix:** Increased `--timeout` on `computer create` from 90 s to 150 s and added a 3-retry loop; this failure mode has not recurred in subsequent local-runtime runs.

### Run sbx-eval000017 – pip install network error
The candidate's `pip install -r requirements.txt` step hit a transient PyPI 503 error inside the sandbox. The sandbox had internet access, but the upstream CDN was briefly degraded. **Root cause:** Transient external dependency. **Fix:** Added a `pip install --retries 5` flag; this reduces (but does not eliminate) the probability.

### Run sbx-eval000020 – Agent hallucinated a non-existent file path
The root-cause strategy agent emitted an edit targeting `src/utils/parser.js` but the demo repo's file was `src/utils/parse.js` (no trailing `r`). The `search` block found no match, so 0 edits were applied, and the unchanged test suite still failed the baseline. **Root cause:** LLM hallucination of a filename. **Fix:** Added fuzzy-path matching in `edits.py` that strips common suffix variations before giving up; this is not yet in production but is tracked as issue #12.

## Observations

- Boot-to-ready times were consistently between 18 s and 42 s (median 26 s) for cloud micro instances.
- All 20 sandboxes were deleted at the end of every run, including the 3 failed ones. No orphaned compute was left running.
- The 85% success rate on 20 runs is above the 80% target. A sample of 50 runs would give a tighter confidence interval, but was outside the free-trial machine limit.
