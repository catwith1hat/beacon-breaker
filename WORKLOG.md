# BeaconBreaker — Work Log

## Goal

Cross-client audit of CL implementations at the **Electra/Pectra** fork
target on mainnet, finding consensus-relevant divergences and producing
fixtures suitable for upstream EF state-tests.

## Clients & Versions

| Client | Repo | Pinned commit | Tag/describe |
|---|---|---|---|
| prysm | github.com/prysmaticlabs/prysm | `d35d65625f` | v3.2.2-rc.1-2539-gd35d65625f |
| lighthouse | github.com/sigp/lighthouse | `176cce585c` | v8.1.3 (shallow) |
| teku | github.com/Consensys/teku | `c05af0eaa0` | 26.4.0-72-gc05af0eaa0 |
| nimbus | github.com/status-im/nimbus-eth2 | `102be79c06` | v26.3.1 |
| lodestar | github.com/ChainSafe/lodestar | `35940ffd61` | v1.42.0-69-g35940ffd61 |
| grandine | github.com/grandinetech/grandine | `eeb33a9228` | 2.0.4-18-geeb33a92 |
| consensus-specs | github.com/ethereum/consensus-specs | `5aa6eec83a` | v0.8.3-7631-g5aa6eec83 |
| consensus-spec-tests | github.com/ethereum/consensus-spec-tests | `bc5c1a7fb2` | v1.6.0-beta.0 (shallow) |
| beacon-APIs | github.com/ethereum/beacon-APIs | `31f7d04f86` | v2.4.1-172-g31f7d04 |

Pinned 2026-05-02. Run `git submodule status` to refresh; bump submodules in
their own commit, separate from any audit item, and re-run any affected
fixtures.

## Fork Target

**Electra/Pectra** on mainnet. Active EIPs in scope:
- EIP-6110 (in-protocol deposits)
- EIP-7002 (EL-triggered exits)
- EIP-7251 (MAX_EFFECTIVE_BALANCE = 2048 ETH, consolidations,
  `0x02` withdrawal-credentials prefix)
- EIP-7549 (move committee index outside attestation signing data)
- EIP-7685 (general execution-layer requests framework)
- EIP-7691 (blob throughput increase) — interacts via Engine API only
- EIP-7623 (calldata cost increase) — EL-side, no direct CL surface

## Areas Investigated

_(Numbered prioritization list. Each entry one line. Candidates above the
"Findings" cutover are forward-looking; candidates below have an
`itemN/README.md`.)_

_None yet. Add the first candidate before starting the loop._

## Speculative Unexplored Areas (2026-05-02)

Initial backlog drawn from §6 of `BEACONBREAKER.md`. Items further down the
list are lower-priority candidates for later iterations.

### Prioritization

1. **`process_consolidation_request` source/target validation** (Pectra,
   EIP-7251) — withdrawal-credentials prefix check, source-not-slashed,
   target-active predicates; balance transfer math.
2. **`process_withdrawal_request` fee escalation** (Pectra, EIP-7002) —
   exponential fee formula, queue caps, source validation.
3. **`process_pending_deposits` queue ordering** (Pectra, EIP-6110) —
   max-deposits-per-slot cap, prioritization vs activation eligibility.
4. **Churn limit calculation at validator-set step boundaries** (Pectra) —
   formula changed; likely divergence vector.
5. **`MAX_EFFECTIVE_BALANCE_ELECTRA` hysteresis** — credit/debit asymmetry
   at the 2048-ETH cap and at the 32-ETH boundary for legacy `0x01` creds.
6. **`process_attestation` with EIP-7549 layout change** — committee index
   moved out of signing data; signature domain implications.
7. **`process_proposer_slashing` `withdrawable_epoch` update** post-Pectra
   churn changes.
8. **`process_attester_slashing` intersection of attesting indices** —
   ordering and dedup semantics across clients.
9. **Per-epoch `process_registry_updates`** — activation queue ordering
   when several validators share `activation_eligibility_epoch`.
10. **`process_slashings`** proportional factor (3x) at the
    `MAX_SLASHABLE_BALANCE_INCREMENT` boundary.
11. **`process_effective_balance_updates`** hysteresis quanta at the
    Pectra `EFFECTIVE_BALANCE_INCREMENT` × hysteresis combination.
12. **`process_pending_consolidations`** — drainage rate, source/target
    coupling, interaction with exits.
13. **State upgrade function at the Pectra activation slot** — new field
    initialization defaults; pending-deposits seeding from EL.
14. **LMD-GHOST `proposer_score_boost`** at slot boundary; behavior under
    equivocation.
15. **`filter_block_tree`** viability under unrealized justification.
16. **SSZ container variable-offset**: overlapping ranges, non-monotonic
    offsets, offset past end.
17. **SSZ list cap**: exactly-N, N+1 rejection, empty-list root.
18. **Bitlist last-bit-set sentinel** — off-by-one on the trailing bit.
19. **Merkleization padding** for non-power-of-2 lists; `mix_in_length`
    correctness across clients.
20. **BLS subgroup membership** for G1 (pubkey) and G2 (signature).
21. **BLS identity / point-at-infinity** handling in pubkey and signature.
22. **`fast_aggregate_verify` with zero pubkeys** — must reject.
23. **Sync committee selection at fork-boundary period rotation**.
24. **Sync committee message verification** — slot-N attests slot-(N-1)
    head; signature aggregation order.
25. **`engine_newPayloadV*` payload-vs-header consistency checks**.
26. **`engine_forkchoiceUpdatedV*` head/safe/finalized validation**.
27. **EL `INVALID` vs `INVALID_BLOCK_HASH` vs `SYNCING`** interpretation.
28. **`requestsHash` propagation** through the Engine API at Pectra.
29. **Validator credential transitions `0x00` → `0x01` → `0x02`** —
    one-way; clients must reject regressions.
30. **Cross-cut: EIP-7251 × EIP-7002** — consolidation pending + EL exit
    in the same block; precedence?

These are candidates for items #1 onward, not findings.

## Findings (per-item bodies)

_None yet._
