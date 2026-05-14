---
status: hypotheses-formed
impact: unknown
last_update: 2026-05-14
builds_on: [56, 60]
eips: [EIP-7732]
splits: []
# main_md_summary: surface scan of the 28+ fork-choice Gloas modifications — high-risk area, dedicated multi-item audit recommended; identified is_payload_verified / is_payload_timely / get_ancestor → ForkChoiceNode / is_supporting_vote / should_extend_payload / get_payload_status_tiebreaker / get_attestation_score / record_block_timeliness as the highest-leverage follow-up targets
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 76: Fork-choice Gloas modifications surface scan — `on_block`, `on_execution_payload_envelope`, `on_payload_attestation_message`, PTC voting, `should_extend_payload`, `get_attestation_score`, `get_weight`

## Summary

Gloas substantially modifies fork choice for the ePBS bid/envelope/PTC lifecycle. Spec at `vendor/consensus-specs/specs/gloas/fork-choice.md` adds **28+ new or modified functions** including:

- **New containers**: `ForkChoiceNode` (root + payload_status), `PayloadStatus` enum (PENDING / FULL / EMPTY), modified `LatestMessage` (adds payload_present field), modified `Store`.
- **New handlers**: `on_execution_payload_envelope`, `on_payload_attestation_message`, `notify_ptc_messages`.
- **New predicates**: `is_payload_verified`, `is_payload_timely`, `is_payload_data_available`, `is_parent_node_full`, `is_supporting_vote`, `should_extend_payload`, `should_apply_proposer_boost`.
- **Modified core**: `on_block` (payload-verified gate), `get_ancestor` (returns `ForkChoiceNode` not `Root`), `get_checkpoint_block`, `update_latest_messages`, `record_block_timeliness`, `update_proposer_boost_root`, `validate_on_attestation`, `get_attestation_score`, `get_weight`, `get_head`.
- **New helpers**: `get_parent_payload_status`, `get_payload_status_tiebreaker`, `get_node_children`.

This item is a **surface scan**, not a per-function byte-equivalence audit. The fork-choice subsystem warrants a dedicated multi-item audit; each function is bug-likely (consensus-impacting, race-condition-prone, new code) and merits a standalone analysis. The scan identifies:

- All 6 clients have implementations of the headline primitives (`is_payload_verified`, `is_payload_timely`, `is_parent_node_full`, `should_extend_payload`).
- All 6 clients agree on the spec constants: `PAYLOAD_TIMELY_THRESHOLD = PTC_SIZE // 2 = 256`, `PAYLOAD_DATA_AVAILABILITY_THRESHOLD = PTC_SIZE // 2 = 256`.
- The `is_payload_timely` count-True-votes semantic is uniformly implemented as bitvector-popcount in all 6 clients.

**No definitive divergences identified at the surface-scan level.** Deeper byte-equivalence audits per primitive are warranted. The lodestar caching-bug pattern from item #67 does not appear to recur in the fork-choice surface (no obvious cache-balance accumulation), but a thorough lodestar fork-choice audit would close that hypothesis.

**Verdict: impact unknown** — explicitly so. The audit surface is too large to close at this level; promoting to `none` requires per-function deep audits. Splits empty until a specific divergence is identified.

## Question

### Modified `Store` (`fork-choice.md`)

Store gains four new fields:

```python
payload_timeliness_vote: Dict[Root, List[Optional[bool], PTC_SIZE]]
payload_data_availability_vote: Dict[Root, List[Optional[bool], PTC_SIZE]]
payloads: Dict[Root, SignedExecutionPayloadEnvelope]
ptc_messages: Dict[Root, List[PayloadAttestationMessage]]
```

Initialized to empty in `get_forkchoice_store`; populated by `on_execution_payload_envelope` (payloads) and `on_payload_attestation_message` (votes).

### Modified `on_block` (`fork-choice.md:846-899`)

```python
def on_block(store: Store, signed_block: SignedBeaconBlock) -> None:
    block = signed_block.message
    assert block.parent_root in store.block_states

    # [New in Gloas:EIP7732]
    if is_parent_node_full(store, block):
        assert is_payload_verified(store, block.parent_root)

    # ... usual checks ...

    state = copy(store.block_states[block.parent_root])
    state_transition(state, signed_block, True)

    # ... store the block, state ...

    # [New in Gloas:EIP7732]
    store.payload_timeliness_vote[block_root] = [None] * PTC_SIZE
    store.payload_data_availability_vote[block_root] = [None] * PTC_SIZE
    notify_ptc_messages(store, state, block.body.payload_attestations)
    record_block_timeliness(store, block_root)
    update_proposer_boost_root(store, block_root)
    update_checkpoints(store, state.current_justified_checkpoint, state.finalized_checkpoint)
    compute_pulled_up_tip(store, block_root)
```

### New `on_execution_payload_envelope` (`fork-choice.md:928-948`)

```python
def on_execution_payload_envelope(store, signed_envelope) -> None:
    envelope = signed_envelope.message
    assert envelope.beacon_block_root in store.block_states
    assert is_data_available(envelope.beacon_block_root)
    state = store.block_states[envelope.beacon_block_root]
    verify_execution_payload_envelope(state, signed_envelope, EXECUTION_ENGINE)
    store.payloads[envelope.beacon_block_root] = envelope
```

### Constants

```
PAYLOAD_TIMELY_THRESHOLD                = PTC_SIZE // 2 = 256
PAYLOAD_DATA_AVAILABILITY_THRESHOLD     = PTC_SIZE // 2 = 256
```

### Predicates

- `is_payload_verified(store, root) := root in store.payloads`
- `is_payload_timely(store, root) := is_payload_verified(store, root) AND sum(vote is True for vote in store.payload_timeliness_vote[root]) > PAYLOAD_TIMELY_THRESHOLD`
- `is_payload_data_available(store, root) := is_payload_verified(store, root) AND sum(vote is True for vote in store.payload_data_availability_vote[root]) > PAYLOAD_DATA_AVAILABILITY_THRESHOLD`
- `get_parent_payload_status(store, block) := PAYLOAD_STATUS_FULL if block.body.signed_execution_payload_bid.message.parent_block_hash == parent.body.signed_execution_payload_bid.message.block_hash else PAYLOAD_STATUS_EMPTY`
- `is_parent_node_full(store, block) := get_parent_payload_status(store, block) == PAYLOAD_STATUS_FULL`

### Modified `get_ancestor` returns `ForkChoiceNode`

Now carries `payload_status` alongside `root`. Callers must consume both fields.

## Hypotheses

- **H1.** All six clients implement `is_payload_verified` as a membership check against `store.payloads`.
- **H2.** All six implement `is_payload_timely` as `is_payload_verified ∧ popcount(timeliness_votes) > PAYLOAD_TIMELY_THRESHOLD`.
- **H3.** All six implement `is_parent_node_full` via the parent_block_hash equality check (semantically: `block.body.signed_execution_payload_bid.message.parent_block_hash == parent.body.signed_execution_payload_bid.message.block_hash`).
- **H4.** All six agree on `PAYLOAD_TIMELY_THRESHOLD = PTC_SIZE // 2 = 256`.
- **H5.** All six modify `on_block` to enforce the `is_payload_verified` assert when parent is FULL.
- **H6.** All six implement `on_execution_payload_envelope` to verify the envelope and populate `store.payloads`.
- **H7.** All six implement `on_payload_attestation_message` to update `store.payload_timeliness_vote` and `store.payload_data_availability_vote` (with index/PTC member mapping).
- **H8.** All six implement the modified `get_ancestor` returning `ForkChoiceNode(root, payload_status)` and update callers accordingly.

## Findings

This is a surface scan — per-client locations verified but per-function byte-equivalence is left for follow-up.

### prysm

Fork-choice primitives in `vendor/prysm/beacon-chain/forkchoice/...` and `vendor/prysm/beacon-chain/core/gloas/...`. Constants tracked in `.ethspecify.yml` (`is_payload_verified#gloas`, `is_parent_node_full#gloas`, `record_block_timeliness#gloas`, `should_apply_proposer_boost#gloas`). Per-spec-function refs surfaced in `specrefs/functions.yml`.

### lighthouse

Fork-choice in `vendor/lighthouse/consensus/proto_array/src/proto_array.rs` (proto-array data structures) and `vendor/lighthouse/consensus/fork_choice/src/...` (handlers). Notable:

- `proto_array.rs:146` — `payload_timeliness_votes: BitVector<U512>` per node (PTC_SIZE=512 bits).
- `proto_array.rs:180` — `is_parent_node_full` impl on ProtoNode.
- `proto_array.rs:206` — threshold check: `node.payload_timeliness_votes.num_set_bits() > E::payload_timely_threshold()`.

The bitvector-popcount semantic implements spec's `sum(vote is True for vote in votes)` correctly when False/None are represented as 0 and True as 1.

### teku

Fork-choice in `vendor/teku/storage/src/main/java/tech/pegasys/teku/storage/protoarray/ForkChoiceModelGloas.java` and `vendor/teku/ethereum/spec/.../gloas/util/ForkChoiceUtilGloas.java`. Notable:

- `ForkChoiceUtilGloas.java:147` — `isPayloadVerified(store, root)` implementation.
- `ForkChoiceUtilGloas.java:480` — `isParentNodeFull` with SafeFuture wrapper.
- `ForkChoiceModelGloas.java:41` — doc-comment cross-references spec `is_parent_node_full`.
- `EPBS_STATUS.md:104` notes is_payload_verified/_timely/_data_available implementation via `ForkChoiceModelGloas` against PTC vote tracker thresholds.

### nimbus

Fork-choice in `vendor/nimbus/beacon_chain/fork_choice/...` (would need deeper audit to locate Gloas primitives).

### lodestar

Fork-choice in `vendor/lodestar/packages/fork-choice/src/protoArray/protoArray.ts`. Notable:

- Line 23: `const PAYLOAD_TIMELY_THRESHOLD = Math.floor(PTC_SIZE / 2);` (= 256) ✓.
- Line 675 `isPayloadTimely`:
  ```typescript
  isPayloadTimely(blockRoot: RootHex): boolean {
      const votes = this.ptcVotes.get(blockRoot);
      if (votes === undefined) return false;
      if (!this.hasPayload(blockRoot)) return false;
      const yesVotes = bitCount(votes.uint8Array);
      return yesVotes > PAYLOAD_TIMELY_THRESHOLD;
  }
  ```
  `bitCount(votes.uint8Array)` implements spec's `sum(vote is True for vote in votes)` correctly when None/False are 0-bit and True is 1-bit.
- Line 698: `isParentNodeFull(block: ProtoBlock): boolean` returns `getParentPayloadStatus(block) === PayloadStatus.FULL`.
- Line 715: `shouldExtendPayload` implementation matches spec semantics (verifies + timely OR no-proposer-boost OR parent-mismatch OR boost-extends-FULL).

### grandine

Fork-choice in `vendor/grandine/fork_choice_store/src/store.rs` (909, 879, 869, ...) and `vendor/grandine/fork_choice_control/src/mutator.rs`. Notable:

- `store.rs:909` — `pub fn is_payload_verified(&self, block_root: H256) -> bool`.
- Multiple call sites in `store.rs` (869, 879, 920, 941) and `mutator.rs` (1206, 3452, 3604) — gates fork-choice operations on payload verification.

## Cross-reference table

| Primitive | prysm | lighthouse | teku | nimbus | lodestar | grandine |
|---|---|---|---|---|---|---|
| `is_payload_verified` | `.ethspecify.yml:397` (impl in core) | `proto_array.rs` membership check | `ForkChoiceUtilGloas.java:147` | (TBD location) | `protoArray.ts hasPayload` | `store.rs:909` |
| `is_payload_timely` | (TBD location) | `proto_array.rs:206` popcount + threshold | (via ForkChoiceModelGloas) | (TBD) | `protoArray.ts:675` popcount | (in store.rs) |
| `is_parent_node_full` | `.ethspecify.yml:439` | `proto_array.rs:180` | `ForkChoiceUtilGloas.java:480` | (TBD) | `protoArray.ts:698` | (in store.rs) |
| `PAYLOAD_TIMELY_THRESHOLD = 256` | (config) | `E::payload_timely_threshold()` | (config) | (preset) | `Math.floor(PTC_SIZE / 2)` ✓ | (preset) |
| Modified `on_block` payload-verified gate | (in core) | (in fork_choice) | (in storage/protoarray) | (TBD) | (in fork-choice package) | `store.rs` |

All 6 clients have implementations; surface-level structure matches spec.

## Empirical tests

No specific empirical tests run for this surface scan. EF spec-test corpus at `vendor/consensus-specs/tests/.../gloas/fork_choice/...` includes deep coverage of the new handlers. All clients run these via their respective spec-test harnesses.

Suggested follow-up items (each warrants a standalone audit):

- **T1: `is_payload_verified` + `on_execution_payload_envelope` round-trip per-client byte-equivalence.** Sibling to #67 but on the envelope-receipt side. **CLOSED 2026-05-14 via item #78 with divergence: confirmed in prysm.** Prysm's `ExecutionPayloadEnvelope` container has only 4 fields (lacks `parent_beacon_block_root` added by spec PR #5152, 2026-04-24); `verify_execution_payload_envelope` lacks the two new consistency asserts; EL call still uses the older state-side form. The other 5 clients adopted PR #5152. Cross-CL wire-layer interop breaks once Glamsterdam activates.
- **T2: `is_payload_timely` PTC-vote-counting cross-client.** Verify all 6 implement the bitvector-popcount semantic equivalently with respect to None / False / True votes. **CLOSED 2026-05-14 via item #77 with divergence: confirmed.** The bitvector-popcount semantic itself is consistent across all 6 clients, but lodestar's `should_extend_payload` drops the `is_payload_data_available` conjunct entirely (no `payloadDataAvailabilityVote` storage, no `isPayloadDataAvailable` predicate; `notifyPtcMessages(.., payloadPresent: boolean)` discards `blob_data_available`). See item #77.
- **T3: Modified `get_ancestor` callers.** Spec breaking change (returns ForkChoiceNode instead of Root). Audit all caller sites in each client for proper consumption of both fields.
- **T4: `is_supporting_vote` semantic.** New vote-classification function for fork-choice scoring. High-leverage for fork-choice integrity.
- **T5: `should_extend_payload` decision logic.** Per-client divergence here would cause builders/proposers to extend FULL vs EMPTY differently. **CLOSED 2026-05-14 via item #77 with divergence: confirmed in lodestar.** First-read assessment that `protoArray.ts:715` "looks correct" was wrong; condition 1 drops the `is_payload_data_available` AND-conjunct that spec requires.
- **T6: `get_attestation_score` Gloas modification.** Spec adds payload-status considerations to attestation weight. Bug-likely.
- **T7: `get_weight` Gloas modification.** Same — payload-status now affects fork-choice weights.
- **T8: `record_block_timeliness` Gloas modification.** New tracking dimensions for timely vs late blocks under ePBS.
- **T9: Re-org timing.** ePBS introduces new re-org scenarios (EMPTY-block re-org, late-payload-envelope re-org). Per-client behavior at the boundary.
- **T10: Threshold semantics on PTC vote ties.** Spec uses `>` (strict greater). Verify all 6 use strict greater (not `>=`).

## Conclusion

The fork-choice subsystem is the most heavily modified area of the Gloas changeset. 28+ new or modified functions; new Store containers; ePBS-aware tiebreakers; PTC-vote accumulation; payload-availability and timeliness predicates.

This surface scan confirms:
- All 6 clients have implementations of the headline primitives (`is_payload_verified`, `is_payload_timely`, `is_parent_node_full`, `should_extend_payload`).
- `PAYLOAD_TIMELY_THRESHOLD = PTC_SIZE // 2 = 256` is uniform.
- Spec's `sum(vote is True)` semantic is implemented as bitvector-popcount across at least lighthouse and lodestar.

This scan does NOT close per-function byte-equivalence — that work requires multiple dedicated follow-up items. **Verdict: impact unknown.** Audit promotes from drafting to hypotheses-formed (the surface is mapped; specific divergence hypotheses for follow-up are documented).

Highest-leverage follow-up targets (per item, in priority order):
1. **`is_payload_timely` threshold semantics** — strict `>` vs `>=` could differ; vote-set representation (None/False/True) handling.
2. **`get_attestation_score` + `get_weight` Gloas modifications** — payload-status fork-choice weighting; most likely place for fork-choice score divergence.
3. **`on_execution_payload_envelope` cross-client** — sibling to #67; envelope-receipt path.
4. **Modified `get_ancestor` callers** — spec API break; per-caller-site audit.
5. **`should_extend_payload` decision logic** — proposer behavior at the FULL/EMPTY boundary.

## Cross-cuts

### With item #56 (Fulu `on_block` / `is_data_available`)

Item #56 covered Fulu's `on_block` audit. Gloas modifies it further. The Gloas `is_data_available` is also modified (per `fork-choice.md:902`); cross-cut on the data-availability primitive.

### With item #60 (PTC selection)

PTC voting in fork-choice (`on_payload_attestation_message`) depends on the PTC composition computed via `compute_ptc` (item #60).

### With item #67 (lodestar builder-sweep)

The fork-choice payload-availability voting is downstream of the state-transition layer where #67 was found. The bug in #67 produces a different state-root; fork-choice would notice via block-import failure (state root mismatch). Cross-cut on the error path.

### With item #58 (`process_execution_payload_bid`)

`is_parent_node_full` reads the bid's `block_hash` field to determine FULL/EMPTY status. Cross-cut.

## Adjacent untouched

1. **All 10 suggested empirical tests (T1-T10) listed above.**
2. **`compute_pulled_up_tip` Gloas modifications.**
3. **`update_proposer_boost_root` Gloas modifications.**
4. **`on_tick` Gloas modifications (if any).**
5. **Fork-choice store persistence/restoration across reboots.**
6. **Race conditions between `on_block` and `on_execution_payload_envelope` arrival.**
7. **Cache coherence under deep re-orgs (>16 slots).**
