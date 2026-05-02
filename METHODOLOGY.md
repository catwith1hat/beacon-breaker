# METHODOLOGY — The BeaconBreaker loop

This is the short form. The full methodology is in `BEACONBREAKER.md`.

## The loop

1. **Pick.** Open `WORKLOG.md` → next prioritization entry. Prefer
   recent-fork code paths, hash/root/signature-deriving code, anything
   touched by multiple EIPs, and items flagged in prior "Adjacent untouched"
   sections.

2. **Hypothesize.** Write down:
   - The specific predicate / value / encoding that could differ.
   - Why it might differ (idiom, library, ambiguous spec, integer math).
   - What input would expose it.
   - Numbered hypotheses H1..Hn that are concrete and falsifiable.

3. **Read all six.** For every client, capture `path:lines` + verbatim
   excerpt of the load-bearing predicate. Build the cross-reference table.

4. **Classify reachability.** C (canonical / honest proposer) > A
   (adversarial within authority) > F (forensic / synthetic block) > M
   (mainnet-impossible). When in doubt, mark F and elevate.

5. **Fixture.** For C/A/F: generate `pre.ssz_snappy`, `block_<n>.ssz_snappy`,
   `post.ssz_snappy`, `meta.yaml` in EF format. Run against all six via
   `scripts/run_fixture.sh itemN/fixture/`. Document the per-client outcome.

6. **Document.** `itemN/README.md` from the §7 template. Update `WORKLOG.md`
   (prioritization line + per-item body). Add "Adjacent untouched" entries
   for future iterations.

7. **Commit.** One item per commit, message format in §12 of
   `BEACONBREAKER.md`. Bisectable history.

## When stuck

- Re-scan prior items' "Adjacent untouched" sections.
- Pivot to **cross-cuts**: compose two EIPs / two spec functions and ask
  "what does the boundary look like?".
- Pivot to **weird corners**: 0, MAX-1, MAX, MAX+1; empty inputs; optional
  fields; cross-fork transitions; integer overflow paths; library
  substitutions; hash-collision-by-key-choice.

## What "done" looks like for one item

- README has all template sections filled.
- Cross-reference table has a row per client.
- Reachability tier declared with justification.
- Fixture generated (or explicit "fixture not applicable, reachability M").
- Fixture run against all six clients with per-client PASS/FAIL recorded.
- WORKLOG updated (top + bottom).
- Adjacent untouched paths listed.
- Single commit on master with the §12 message format.
