# Item Table of Contents

All items in this audit, sorted by number. For only the items that produced a confirmed cross-client divergence, see the Active findings table on the [project README](README.md).

| # | Title | Status |
|---|---|---|
| [#1](items/001/) | `process_effective_balance_updates` Pectra hysteresis with `MAX_EFFECTIVE_BALANCE_ELECTRA` | source-code-reviewed |
| [#2](items/002/) | `process_consolidation_request` EIP-7251 switch + main path | source-code-reviewed |
| [#3](items/003/) | `process_withdrawal_request` EIP-7002 full-exit + partial paths | source-code-reviewed |
| [#4](items/004/) | `process_pending_deposits` EIP-6110 per-epoch drain | source-code-reviewed |
| [#5](items/005/) | `process_pending_consolidations` EIP-7251 drain side | source-code-reviewed |
| [#6](items/006/) | `process_voluntary_exit` + `initiate_validator_exit` Pectra | source-code-reviewed |
| [#7](items/007/) | `process_attestation` EIP-7549 multi-committee aggregation | source-code-reviewed |
| [#8](items/008/) | `process_attester_slashing` (EIP-7549 + EIP-7251) | source-code-reviewed |
| [#9](items/009/) | `process_proposer_slashing` (slash_validator pair, Pectra-affected) | source-code-reviewed |
| [#10](items/010/) | `process_slashings` per-epoch + `process_slashings_reset` (EIP-7251 algorithm restructure) | source-code-reviewed |
| [#11](items/011/) | `upgrade_to_electra` state-upgrade function (Track C #13, foundational) | source-code-reviewed |
| [#12](items/012/) | `process_withdrawals` Pectra-modified (EIP-7251 partial-queue drain) | source-code-reviewed |
| [#13](items/013/) | `process_operations` Pectra dispatcher (EIP-6110 cutover + EIP-7685 requests routing) | source-code-reviewed |
| [#14](items/014/) | `process_deposit_request` (EIP-6110, brand-new in Pectra) | source-code-reviewed |
| [#15](items/015/) | `get_execution_requests_list` + `requestsHash` (EIP-7685, CL→EL boundary) | source-code-reviewed |
| [#16](items/016/) | `compute_exit_epoch_and_update_churn` + `compute_consolidation_epoch_and_update_churn` (Pectra-NEW per-block churn-budget primitives) | source-code-reviewed |
| [#17](items/017/) | `process_registry_updates` Pectra-modified (single-pass restructure + EIP-7251 eligibility predicate) | source-code-reviewed |
| [#18](items/018/) | `add_validator_to_registry` + `get_validator_from_deposit` Pectra-modified | source-code-reviewed |
| [#19](items/019/) | `process_execution_payload` Pectra-modified (EIP-7691 blob limit + EIP-7685 requests pass-through) | source-code-reviewed |
| [#20](items/020/) | `apply_pending_deposit` + `is_valid_deposit_signature` (Pectra-NEW per-deposit application + EIP-7044-style signature pinning) | source-code-reviewed |
| [#21](items/021/) | `queue_excess_active_balance` (Pectra-NEW placeholder-PendingDeposit producer) | source-code-reviewed |
| [#22](items/022/) | Compounding/credential subsystem helpers (predicates + `switch_to_compounding_validator`) | final |
| [#23](items/023/) | `get_pending_balance_to_withdraw` (Pectra-NEW exit-gating accessor) | final |
| [#24](items/024/) | `is_valid_switch_to_compounding_request` (Pectra-NEW 6-check security gate for the switch path) | source-code-reviewed |
| [#25](items/025/) | `is_valid_indexed_attestation` (Pectra-MODIFIED via SSZ-type capacity expansion) | source-code-reviewed |
| [#26](items/026/) | `get_attesting_indices` + `get_committee_indices` (Pectra-MODIFIED + Pectra-NEW for EIP-7549 multi-committee aggregation) | source-code-reviewed |
| [#27](items/027/) | `get_next_sync_committee_indices` (Pectra-MODIFIED + Gloas-MODIFIED for balance-weighted sync committee selection) | source-code-reviewed |
| [#28](items/028/) | Cross-corpus pre-emptive Gloas-fork divergence consolidated tracking audit | final |
| [#29](items/029/) | `compute_signing_root` / `compute_domain` / `compute_fork_data_root` / `get_domain` cross-client byte-for-byte equivalence audit | source-code-reviewed |
| [#30](items/030/) | `get_beacon_proposer_index` + `process_proposer_lookahead` + `initialize_proposer_lookahead` + `compute_proposer_indices` + `get_beacon_proposer_indices` (Fulu-NEW EIP-7917 deterministic proposer lookahead) | source-code-reviewed |
| [#31](items/031/) | `get_blob_parameters(epoch)` + `blob_schedule` schema + Fulu-modified `compute_fork_digest` (EIP-7892 BPO hardforks) | source-code-reviewed |
| [#32](items/032/) | `process_execution_payload` Fulu-modified (item #19 Fulu equivalent; REMOVED at Gloas) | source-code-reviewed |
| [#33](items/033/) | `get_custody_groups` + `compute_columns_for_custody_group` (EIP-7594 PeerDAS custody foundation) | source-code-reviewed |
| [#34](items/034/) | `verify_data_column_sidecar` + `verify_data_column_sidecar_kzg_proofs` + `verify_data_column_sidecar_inclusion_proof` (EIP-7594 PeerDAS sidecar validation pipeline) | source-code-reviewed |
| [#35](items/035/) | `is_data_available` Fulu fork-choice rewrite (EIP-7594 PeerDAS column-based DAS in fork choice) | source-code-reviewed |
| [#36](items/036/) | `upgrade_to_fulu` standalone audit (item #11 Fulu equivalent) | source-code-reviewed |
| [#37](items/037/) | `compute_subnet_for_data_column_sidecar` + `DATA_COLUMN_SIDECAR_SUBNET_COUNT` (EIP-7594 PeerDAS gossip subnet derivation) | source-code-reviewed |
| [#38](items/038/) | `get_validators_custody_requirement` (EIP-7594 PeerDAS validator-balance-scaled custody) | source-code-reviewed |
| [#39](items/039/) | `compute_matrix` + `recover_matrix` (EIP-7594 PeerDAS Reed-Solomon extension/recovery) | source-code-reviewed |
| [#40](items/040/) | `get_data_column_sidecars` (EIP-7594 PeerDAS validator-side sidecar construction) | source-code-reviewed |
| [#41](items/041/) | ENR `cgc` (custody group count) field encoding/decoding (EIP-7594 PeerDAS peer discovery) | source-code-reviewed |
| [#42](items/042/) | ENR `nfd` (next fork digest) field encoding/decoding (EIP-7594/EIP-7892 PeerDAS peer discovery) | source-code-reviewed |
| [#43](items/043/) | Fulu / Gloas Engine API surface (`engine_newPayloadV4` + `engine_getPayloadV5` + `engine_getBlobsV2` at Fulu; `engine_newPayloadV5` + `engine_getPayloadV6` + `engine_forkchoiceUpdatedV4` Gloas-NEW) | source-code-reviewed |
| [#44](items/044/) | `PartialDataColumnSidecar` family (`verify_partial_data_column_header_inclusion_proof` + `verify_partial_data_column_sidecar_kzg_proofs` at Fulu; container reshape + `PartialDataColumnGroupID` at Gloas) | source-code-reviewed |
| [#45](items/045/) | MetaData v3 SSZ container + GetMetaData v3 RPC (`/eth2/beacon_chain/req/metadata/3/`) — EIP-7594 PeerDAS metadata layer | source-code-reviewed |
| [#46](items/046/) | `DataColumnSidecarsByRange v1` + `DataColumnSidecarsByRoot v1` RPC handlers (Fulu-NEW) + Gloas-NEW `ExecutionPayloadEnvelopesByRange/ByRoot v1` Req/Resp surface | source-code-reviewed |
| [#47](items/047/) | Status v2 RPC handshake (`/eth2/beacon_chain/req/status/2/`) — Fulu-NEW with `earliest_available_slot` | source-code-reviewed |
| [#48](items/048/) | Cross-corpus forward-fragility pattern catalogue (Patterns A–CC across items #1–#47) — Glamsterdam refresh | source-code-reviewed |
| [#49](items/049/) | `compute_max_request_data_column_sidecars()` formula consistency — Fulu-NEW RPC response cap (`MAX_REQUEST_BLOCKS_DENEB * NUMBER_OF_COLUMNS`) | source-code-reviewed |
| [#50](items/050/) | `MAX_REQUEST_BLOB_SIDECARS_ELECTRA` formula consistency + Fulu deprecation handling for `BlobSidecarsByRange v1` + `BlobSidecarsByRoot v1` | source-code-reviewed |
| [#51](items/051/) | `blob_sidecar_{subnet_id}` gossip topic Fulu deprecation handling — Pattern GG gossip-layer deprecation cohort | source-code-reviewed |
| [#52](items/052/) | `MAX_REQUEST_BLOCKS_DENEB` foundational cap — Deneb-heritage constant feeding 8 RPC use-sites across Deneb → Electra → Fulu → Gloas | source-code-reviewed |
| [#53](items/053/) | `DataColumnsByRootIdentifier` SSZ container audit — Fulu-NEW container consumed by `DataColumnSidecarsByRoot v1`; Pattern AA + FF scope expansion | source-code-reviewed |
| [#54](items/054/) | `DataColumnSidecar` SSZ container — Fulu 6-field + Gloas 5-field reshape (EIP-7732); Pattern HH depth baking; Pattern M cohort extends | source-code-reviewed |
| [#55](items/055/) | `MIN_EPOCHS_FOR_DATA_COLUMN_SIDECARS_REQUESTS` retention period — Fulu-NEW operator-tunable; Pattern AA + FF carry-forward; no Pattern HH baking | source-code-reviewed |
| [#56](items/056/) | Fulu + Gloas fork choice modifications — `is_data_available` (PeerDAS-modified at Fulu, again modified at Gloas) + `on_block` (DA delayed to `on_execution_payload_envelope` at Gloas) — Pattern II fork-choice DA architecture divergence | source-code-reviewed |
| [#57](items/057/) | `process_builder_pending_payments` (Gloas-new epoch helper, EIP-7732 ePBS settlement) | source-code-reviewed |
| [#58](items/058/) | `process_execution_payload_bid` (Gloas-new block-time bid validation, EIP-7732 ePBS) | source-code-reviewed |
| [#59](items/059/) | `verify_execution_payload_envelope` + `on_execution_payload_envelope` (Gloas fork-choice envelope verification, EIP-7732 ePBS) | source-code-reviewed |
| [#60](items/060/) | Payload Timeliness Committee (PTC) selection + `process_payload_attestation` + `is_valid_indexed_payload_attestation` | source-code-reviewed |
| [#61](items/061/) | `compute_activation_exit_epoch` foundational primitive | source-code-reviewed |
| [#62](items/062/) | `requestsHash` cross-client byte-for-byte Merkleization equivalence (EIP-7685, CL-EL boundary) | source-code-reviewed |
| [#63](items/063/) | `process_ptc_window` epoch helper | source-code-reviewed |
| [#64](items/064/) | `upgrade_to_gloas` fork-upgrade migration | source-code-reviewed |
| [#65](items/065/) | `process_proposer_slashing` Gloas modification — `BuilderPendingPayment` voidance | source-code-reviewed |
| [#66](items/066/) | `apply_pending_deposit` Gloas modifications — 0x03 credentials + builders-registry interaction | source-code-reviewed |
| [#67](items/067/) | Builder withdrawal flow — `state.builder_pending_withdrawals` lifecycle + 0x03 sweep + apply_withdrawals dispatch | fuzzed |
| [#68](items/068/) | `compute_balance_weighted_selection` triple-call cross-cut | source-code-reviewed |
| [#69](items/069/) | `DOMAIN_*` constants byte-by-byte cross-client audit | source-code-reviewed |
| [#70](items/070/) | `engine_newPayloadV5` schema + V4↔V5 dispatch | source-code-reviewed |
| [#71](items/071/) | `engine_getPayloadV5` builder-vs-self-build dispatch | source-code-reviewed |
| [#72](items/072/) | PeerDAS custody column selection — runtime usage of the `cgc` field | source-code-reviewed |
| [#73](items/073/) | `get_data_column_sidecars` construction at Gloas | source-code-reviewed |
| [#74](items/074/) | `process_voluntary_exit` Gloas builder-exit branch + `process_attestation` builder-payment-weight accumulation | source-code-reviewed |
