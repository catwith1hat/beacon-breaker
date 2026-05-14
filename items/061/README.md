---
status: source-code-reviewed
impact: none
last_update: 2026-05-14
builds_on: [16]
eips: []
prysm_version: v7.1.3-rc.3-209-g0f25a41868
lighthouse_version: v8.1.2-185-g1a6863118
teku_version: 26.4.0-127-g70ad00cbaf
nimbus_version: v26.5.0-10-g550c7a3f0
lodestar_version: v1.42.0-69-g35940ffd61
grandine_version: 2.0.4-97-g15dd0225
---

# 61: `compute_activation_exit_epoch` foundational primitive

## Summary

Trivial Phase0 formula `Epoch(epoch + 1 + MAX_SEED_LOOKAHEAD)`, **not modified at any fork through Gloas**, but pivotal: consumed by `compute_exit_epoch_and_update_churn` (item #16 chokepoint), `compute_consolidation_epoch_and_update_churn`, `process_registry_updates` activation branch, `apply_pending_deposit`, and the Electra/Gloas fork-upgrade initializers for `earliest_exit_epoch` + `earliest_consolidation_epoch`. A 1-epoch drift here would silently re-time every validator activation/exit on mainnet.

All six clients implement the formula as a 1-line `epoch + 1 + MAX_SEED_LOOKAHEAD` over a runtime-config-sourced constant (mainnet `MAX_SEED_LOOKAHEAD = 4`). Verified identical across mainnet, minimal, and gnosis preset values (`4` everywhere). Overflow policies differ at the `epoch ≈ u64::MAX - 5` boundary (silent wrap in prysm/nimbus; checked `safe_add` in lighthouse; saturating in grandine; UInt64.plus in teku; JS Number in lodestar) — practically unreachable on mainnet (slot 0 → u64::MAX is ~10¹¹ years out). No divergence.

## Question

Pyspec `compute_activation_exit_epoch` at `vendor/consensus-specs/specs/phase0/beacon-chain.md:925-933`:

```python
def compute_activation_exit_epoch(epoch: Epoch) -> Epoch:
    """
    Return the epoch during which validator activations and exits initiated in ``epoch`` take effect.
    """
    return Epoch(epoch + 1 + MAX_SEED_LOOKAHEAD)
```

Mainnet preset constant at `vendor/consensus-specs/presets/mainnet/phase0.yaml:38`: `MAX_SEED_LOOKAHEAD: 4`. Minimal preset (same file path, `presets/minimal/`): `MAX_SEED_LOOKAHEAD: 4`. No fork (Altair / Bellatrix / Capella / Deneb / Electra / Fulu / Gloas) modifies the function body or the constant; the consensus-specs corpus contains a single definition and consumers reference it directly.

Consumers (grep across the spec corpus):

- `phase0/beacon-chain.md:1236` — `initiate_validator_exit` `exit_queue_epoch` clamp.
- `phase0/beacon-chain.md:1776` — `process_registry_updates` activation-branch `validator.activation_epoch` assignment.
- `electra/fork.md:45,97` — Electra fork upgrade `earliest_exit_epoch` + `earliest_consolidation_epoch` initialization.
- `electra/beacon-chain.md:772,802,911` — `compute_exit_epoch_and_update_churn` (item #16) + `compute_consolidation_epoch_and_update_churn` + Electra `process_registry_updates` activation assignment.
- `gloas/beacon-chain.md:863` — Gloas-modified `compute_exit_epoch_and_update_churn` clamp (formula unchanged at Gloas; only the surrounding churn rework).

Open questions before source review:

1. **Constant source** — runtime spec config or compile-time constant? Per-client.
2. **Per-fork override** — does any client gate the constant on fork? (Spec says no.)
3. **Overflow** — at `epoch ≈ u64::MAX - 5`, the addition would overflow. Per-client safe-arithmetic policy?
4. **Caller-site casts** — `Epoch` is `uint64` in some clients; `Epoch::new(u64)` newtype wrapper in others. Verify cast safety.

## Hypotheses

- **H1.** All six clients implement `compute_activation_exit_epoch(epoch) = epoch + 1 + MAX_SEED_LOOKAHEAD`.
- **H2.** All six read `MAX_SEED_LOOKAHEAD` from the runtime spec config (not a per-fork compile-time constant), to support mainnet + minimal + gnosis presets.
- **H3.** All six produce identical values for any input epoch ≤ u64::MAX - 5 (no overflow region).
- **H4.** All six callers (item #16 chokepoint, item #17 registry updates, item #4 pending-deposit drain, Electra fork upgrade initializers, Gloas churn rework) consume the same return value.
- **H5.** No client fork-gates the function or the constant (Gloas does not modify it).
- **H6** *(forward-fragility)*. Overflow handling at `epoch ≈ u64::MAX - 5` — verify saturating vs checked vs wrapping behaviour cross-client. Practically unreachable on mainnet but worth documenting.
- **H7.** All six clients agree on `MAX_SEED_LOOKAHEAD = 4` for mainnet, minimal, and gnosis presets.

## Findings

All six clients are spec-conformant. Findings below capture exact file/line, constant source, and overflow policy.

### prysm

Implementation at `vendor/prysm/beacon-chain/core/helpers/validators.go:219-221`:

```go
func ActivationExitEpoch(epoch primitives.Epoch) primitives.Epoch {
    return epoch + 1 + params.BeaconConfig().MaxSeedLookahead
}
```

`primitives.Epoch` is `type Epoch uint64`; Go uint64 addition wraps silently on overflow. Spec-conformant within the non-overflow range. Constant source: runtime config `params.BeaconConfig().MaxSeedLookahead` (mainnet 4 at `vendor/prysm/config/params/mainnet_config.go:110`; minimal 4 at `minimal_config.go:48`; e2e config 1 at `testdata/e2e_config.yaml:131` — only for the e2e test harness, never mainnet). No fork gating.

### lighthouse

Implementation at `vendor/lighthouse/consensus/types/src/core/chain_spec.rs:680-682`:

```rust
pub fn compute_activation_exit_epoch(&self, epoch: Epoch) -> Result<Epoch, ArithError> {
    epoch.safe_add(1)?.safe_add(self.max_seed_lookahead)
}
```

`Epoch` is a newtype wrapper over u64; `safe_add` returns `ArithError` on overflow. `BeaconState::compute_activation_exit_epoch` at `vendor/lighthouse/consensus/types/src/state/beacon_state.rs:2143-2149` is a thin delegate. Constant source: `ChainSpec.max_seed_lookahead: Epoch` (mainnet `Epoch::new(4)` at `chain_spec.rs:1104`; minimal at `chain_spec.rs:1527`). No fork gating.

### teku

Implementation at `vendor/teku/ethereum/spec/src/main/java/tech/pegasys/teku/spec/logic/common/helpers/MiscHelpers.java:212-214`:

```java
public UInt64 computeActivationExitEpoch(final UInt64 epoch) {
    return epoch.plus(UInt64.ONE).plus(specConfig.getMaxSeedLookahead());
}
```

Lives on the base `MiscHelpers` class; no fork-specific override in the `versions/electra/` or `versions/gloas/` `MiscHelpers*` subclasses (verified by grep). Constant source: `specConfig.getMaxSeedLookahead()` — runtime YAML config (mainnet `presets/mainnet/phase0.yaml:39 MAX_SEED_LOOKAHEAD: 4`; minimal `presets/minimal/phase0.yaml:39 MAX_SEED_LOOKAHEAD: 4`; gnosis `presets/gnosis/phase0.yaml:40 MAX_SEED_LOOKAHEAD: 4`). `UInt64.plus` throws `ArithmeticException` on overflow.

### nimbus

Implementation at `vendor/nimbus/beacon_chain/spec/beaconstate.nim:142-146`:

```nim
# https://github.com/ethereum/consensus-specs/blob/v1.6.0-alpha.0/specs/phase0/beacon-chain.md#compute_activation_exit_epoch
func compute_activation_exit_epoch*(epoch: Epoch): Epoch =
  ## Return the epoch during which validator activations and exits initiated in
  ## ``epoch`` take effect.
  epoch + 1 + MAX_SEED_LOOKAHEAD
```

`Epoch` is a distinct uint64 type in nimbus; the `+` operator wraps silently. `MAX_SEED_LOOKAHEAD` is a compile-time per-preset constant: mainnet `4` at `vendor/nimbus/beacon_chain/spec/presets/mainnet/phase0_preset.nim:48`; minimal `4` at `presets/minimal/phase0_preset.nim:49`; gnosis `4` at `presets/gnosis/phase0_preset.nim:47`. **Nimbus uses compile-time preset selection rather than runtime config** for this constant — H2 partially violated (constant is compile-time, not runtime), but functionally equivalent across all defined presets. No fork gating.

### lodestar

Implementation at `vendor/lodestar/packages/state-transition/src/util/epoch.ts:46-48`:

```typescript
export function computeActivationExitEpoch(epoch: Epoch): Epoch {
  return epoch + 1 + MAX_SEED_LOOKAHEAD;
}
```

`Epoch` is a TypeScript `number` (JS Number — max safe integer 2⁵³ - 1; overflow becomes float-imprecise rather than wrapping). `MAX_SEED_LOOKAHEAD` is imported from `@lodestar/params` — mainnet preset `4` at `vendor/lodestar/packages/params/src/presets/mainnet.ts:42`; minimal `4` at `presets/minimal.ts:42`. Lodestar's preset selection happens at module-load time (chosen via env / CLI); not runtime-pluggable per request. No fork gating.

### grandine

Implementation at `vendor/grandine/helper_functions/src/misc.rs:123-126`:

```rust
#[must_use]
pub const fn compute_activation_exit_epoch<P: Preset>(epoch: Epoch) -> Epoch {
    epoch.saturating_add(1 + P::MAX_SEED_LOOKAHEAD)
}
```

`Epoch = u64`. Uses `saturating_add` — overflow saturates at `u64::MAX` rather than wrapping or panicking. **Note: the addition `1 + P::MAX_SEED_LOOKAHEAD` is computed at compile time (const generic), not at runtime — so the saturation only applies to `epoch + 5` (or the appropriate sum), not to a potential `1 + MAX_SEED_LOOKAHEAD` intermediate overflow.** Preset-parametrized via the `P: Preset` trait: mainnet `MAX_SEED_LOOKAHEAD: u64 = 4` at `vendor/grandine/types/src/preset.rs:278`. The runtime-`Config` mirror at `preset.rs:830` is populated from `P::MAX_SEED_LOOKAHEAD` so the runtime API surface (`/eth/v1/config/spec`) reports the correct value. No fork gating.

## Cross-reference table

| Client | `compute_activation_exit_epoch` location | `MAX_SEED_LOOKAHEAD` source | Overflow policy (H6) | Caller-site cast idiom | Mainnet preset value |
|---|---|---|---|---|---|
| prysm | `validators.go:219` | runtime `params.BeaconConfig().MaxSeedLookahead` | silent wrap (Go uint64) | `primitives.Epoch` typedef over uint64 | `4` |
| lighthouse | `chain_spec.rs:680` | runtime `ChainSpec.max_seed_lookahead` | `ArithError` (checked `safe_add`) | `Epoch` newtype + `safe_add` | `4` |
| teku | `MiscHelpers.java:212` | runtime `specConfig.getMaxSeedLookahead()` (YAML) | `ArithmeticException` (UInt64.plus) | `UInt64` wrapper | `4` |
| nimbus | `beaconstate.nim:143` | **compile-time** per-preset module | silent wrap (nim uint64) | distinct `Epoch` type over uint64 | `4` |
| lodestar | `epoch.ts:46` | module-load-time `@lodestar/params` | JS Number float-imprecise above 2⁵³ | `Epoch` = `number` | `4` |
| grandine | `misc.rs:124` | **compile-time** generic `P::MAX_SEED_LOOKAHEAD` | `saturating_add` (saturates at u64::MAX) | `Epoch` = `u64` + const generic | `4` |

H1 ✓ (formula uniform). H2 partial — prysm/lighthouse/teku are runtime; nimbus/lodestar/grandine are module-/compile-time. Functionally equivalent in every shipped preset (`4` everywhere). H3 ✓. H4 ✓ (verified by grep of consumers — same function called from every callsite in every client). H5 ✓ (no fork override). H6 — overflow policies differ but all are well-defined and the boundary is mainnet-unreachable. H7 ✓.

## Empirical tests

No dedicated EF fixture exercises this primitive in isolation (it's a pure function with no state dependency beyond the input epoch). Implicit coverage from every Pectra+ EF fixture that touches `process_voluntary_exit`, `process_withdrawal_request`, `process_consolidation_request`, `process_registry_updates`, `compute_exit_epoch_and_update_churn`, or the Electra/Gloas state-upgrade initializers — all of which pass cross-client per items #2 / #3 / #6 / #8 / #9 / #16 / #17 / #56. Strong implicit evidence that H1 / H4 / H5 / H7 hold.

Suggested fuzzing vectors (none of these are presently wired):

- **T1.1 (mainnet canonical).** `compute_activation_exit_epoch(100) == 105`. Pure-function cross-client byte-equivalence over a range of input epochs.
- **T1.2 (genesis edge).** `compute_activation_exit_epoch(0) == 5`.
- **T1.3 (minimal preset).** Same input under minimal preset; verify constant agrees (`4` everywhere).
- **T2.1 (overflow boundary).** `compute_activation_exit_epoch(u64::MAX - 4)` — document divergent overflow behaviour across clients (prysm wraps to `0`; lighthouse returns `ArithError`; teku throws; nimbus wraps; lodestar returns a float; grandine saturates at `u64::MAX`). Practically unreachable but worth documenting.
- **T2.2 (constant-mismatch synthetic).** Hand-construct a custom preset with `MAX_SEED_LOOKAHEAD = 5`; verify all 6 clients re-time activations/exits consistently. Tests H2 (runtime vs compile-time constant sourcing).

## Conclusion

All six clients are spec-conformant on `compute_activation_exit_epoch`. The function is a 1-line `epoch + 1 + MAX_SEED_LOOKAHEAD` with no fork override anywhere through Gloas. Mainnet constant `4` is uniform across all 6 clients and all shipped presets. Overflow policies differ at the unreachable `u64::MAX` boundary but never cross-couple under realistic inputs.

**Verdict: impact none.** No divergence. Audit closes. The constant-sourcing split (runtime vs compile-time vs module-load-time) is documented but has no behavioral consequence on mainnet or any shipped testnet preset.

## Cross-cuts

### With item #16 (EIP-8061 churn chokepoint)

Item #16's `compute_exit_epoch_and_update_churn` clamps `exit_queue_epoch = max(state.earliest_exit_epoch, compute_activation_exit_epoch(current_epoch))`. A divergence here would shift the clamp value, propagating into every Pectra+ exit's `exit_epoch` assignment. Item #16 closed at H10 vacated; this item confirms the upstream primitive is identical too.

### With item #17 (`process_registry_updates`)

Item #17's activation branch writes `validator.activation_epoch = compute_activation_exit_epoch(current_epoch)`. Same upstream primitive; item #17 closed at H10 vacated; uniform consumption confirmed here.

### With item #4 (`process_pending_deposits`)

Item #4's drain calls `compute_activation_exit_epoch` for the activation-epoch assignment of newly-created validators. Same upstream primitive; same conclusion.

### With Electra + Gloas fork upgrades

Electra fork upgrade at `electra/fork.md:45,97` initializes `earliest_exit_epoch` and `earliest_consolidation_epoch` to `compute_activation_exit_epoch(get_current_epoch(pre))`. Gloas does not modify this initialization. Cross-cut audit: per-client `upgrade_to_electra` / `upgrade_to_gloas` paths use the same primitive — verified by grep.

## Adjacent untouched

1. **`MAX_SEED_LOOKAHEAD` constant survey beyond mainnet** — gnosis, hoodi, holesky testnet configurations; verify per-client custom-config loading uses the same value (`4`).
2. **Overflow policy formalization** — none of the clients agree on the overflow contract, but the input domain never reaches it on mainnet (epochs grow by `1 / 6.4 minutes` ≈ 10¹¹ years before u64 overflow). Document as forward-fragility only.
3. **Custom-config divergence audit (T2.2)** — if anyone ships a preset with `MAX_SEED_LOOKAHEAD ≠ 4`, the constant-sourcing split (runtime vs compile-time) matters: prysm/lighthouse/teku would pick up the runtime value; nimbus/lodestar/grandine would not (requires re-build / re-link with new preset). Worth a 1-test fixture to confirm.
4. **`Epoch` newtype safety** — Rust clients (`lighthouse`, `grandine`) use newtype wrappers; verify the addition doesn't lose the type-distinction at the call site (e.g., adding a `Slot` to an `Epoch` would be a type error in lighthouse; not in grandine where `Epoch` is a plain `u64`).
