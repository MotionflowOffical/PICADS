# PICADS — post-v1.0 feature roadmap

**Status:** planned / deferred. This is a scope-control document, not a list of features required before the first usable PICADS release. It does not imply that the features exist today.

## Baseline contract for PICADS v1.0

The first feature-complete release must demonstrate a reproducible **source → MCD/CO compilation → DLS simulation and checked RTL → real synthesis → standard-cell physical implementation → independently inspected GDSII** workflow for a clearly documented subset of supported designs and a supported, usable PDK. The GUI must launch and the external-tool configuration must work on the supported Windows installation. A successful physical run must include real tool logs and artifact provenance, not simulated or fabricated success.

Manufacturing-qualified signoff additionally requires process-authorized rule decks and verification across the required electrical corners. When unavailable, PICADS must explicitly report **NOT QUALIFIED**, regardless of whether a GDSII was generated. Arbitrary high-level programs, custom TFT electrical models and every possible PDK are not conditions of v1.0.

## Deferred feature groups

| Priority after v1.0 | Feature | Why deferred |
|---|---|---|
| v1.x | Multiple transactions per source process, dynamic transaction IDs, reorder buffers | Improves throughput; not necessary for a verified first chip |
| v1.x | Globally shared variable-latency custom operators | Optimizes scheduling after baseline RTL and physical flow work |
| v1.x | Automatic cost-driven area/power/timing optimization | Requires calibrated cell-library metrics and real synthesis evidence |
| v1.x | More Python semantics, extended signed arithmetic, additional C/C++ constructs | Expands the supported language, not the minimum end-to-end capability |
| v1.x | Multibank SRAM inference and source-level interprocess synchronization | Needed for larger designs; a bounded on-chip memory is sufficient initially |
| v2.x | AXI4 burst transfers, DMA controllers, multiple outstanding external memory operations | Advanced integration and throughput features |
| v2.x | Cache coherence and processor/multicore interconnects | Specialized system-level hardware capability |
| v2.x | Speculative/event-driven HLS with arbitrary concurrent loops and dependencies | Research-level extension beyond an explicitly restricted v1 language |
| v2.x | Advanced formal liveness, full-system concurrency proofs, automatic proof partitioning | Broader confidence after verified baseline checks exist |
| v2.x | Multi-die, analog/mixed signal automation and heterogeneous processes | Requires substantially different verification and PDK infrastructure |

## V1.0 blockers — NOT optional enhancements

1. Define and enforce the language and chip sizes supported by v1.0; unsupported input must fail with an actionable diagnostic.
2. Verify exported RTL against the logical design with native tools on the user machine.
3. Make Yosys/LibreLane physical runs reproducible: explicit tool versions, selected PDK, constraints, clean run tag, logs, file hashes and final layout evidence.
4. Fix and runtime-test the Qt GUI project/edit/simulate/dependency/physical-flow path.
5. Demonstrate an end-to-end RTL → GDSII flow using a valid standard-cell PDK, with no fake results.
6. Report actual DRC/LVS/timing evidence separately; do not call a file 'manufacturing ready' without the qualified foundry evidence.
7. Provide a one-command Windows/WSL validation run that collects failure logs without manual test scripting.

## Change control

New features belong here unless (a) they unblock one of the v1.0 acceptance checks or (b) they fix correctness, security, reproducibility or data loss. The v1.0 target is an end-to-end demonstrable integrated-circuit design workflow, not an ever-growing list of protocols.
