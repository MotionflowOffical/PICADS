# Diagnostic and recovery handbook

## Stable structure

Every issue is a JSON object with `code`, `severity`, `origin`, `stage`, `message`, `file`, `line`, `column`, `cause`, `remedy`, `evidence`, `blocked_by`, `issue_id`.

Independent origin classifications: `SOURCE`, `MCD`, `CO`, `DLS`, `GENERATOR`, `SIMULATOR`, `VERIFIER`, `CONFIG`, `DEPENDENCY`, `TOOL`, `PHYSICAL`, `FILESYSTEM`, `INTERNAL`.

- `SOURCE.UNDEFINED_SYMBOL`: source refers to an undefined input/local.
- `SOURCE.FRONTEND_UNSUPPORTED`: user selected a currently unsupported language frontend.
- `MCD.BAD_TOP` / `CO.BAD_VALUE`: invalid user project settings, not generator bugs.
- `SOURCE.UNSUPPORTED`: source uses a construct that the frontend cannot compile.
- `VERIFY.MISMATCH`: numeric reference disagrees with DLS; captured counterexample is provided.
- `TOOL.MISSING`: executable missing; includes actual program name and invocation.
- `TOOL.EXIT_NONZERO`: native EDA utility returned nonzero; read the stage's stdout/stderr log.
- `PIPELINE.BLOCKED`: dependent stage did not run; inspect `blocked_by`. It is not a separate failure.
- `INTERNAL.UNEXPECTED`: unexpected exception in application code; exception type and traceback are included.
- `PHYSICAL.SIGNOFF_UNVERIFIED`: tool exit is not enough to claim masks ready for manufacturing.

## New v0.2.0 issue families

- `C.PARSE` / `C.UNSUPPORTED_TYPE` / `C.PREPROCESSOR`: source-language problem, never labeled an EDA routing fault.
- `C.NATIVE_MISMATCH`: original independently compiled C/C++ output differs from generated DLS; evidence carries the first reproducer.
- `CO.RESOURCE_LIMIT`: CO operation-count cap incompatible with the generated architecture; evidence gives operation kinds, widths and source lines.
- `MCD.FUNCTION_NOT_FOUND`: MCD asks for an implementation absent from the source.
- `PHYSICAL.ARTIFACT_INVALID`: external flow appeared to finish but actual current-run GDS was missing/invalid or reported checks failed.
- `PHYSICAL.CHECKS_UNVERIFIED`: missing or unrecognized DRC, LVS, antenna or timing data is not treated as a pass.
- `GDS.*`: read-only GDSII structural inspection error, not a manufacturing-rule violation.

Every ordinary build moves the preceding `build/latest` into `build/history/` before starting anew, so stale reports and old GDS files cannot masquerade as current output. Individual log events always include a `run_id`; history directories are retained until explicitly cleaned by the user.

## Debug workflow

1. Open `build/latest/report.json`. Find ERROR issues and their IDs before inspecting BLOCKED stages.
2. Inspect `file`, `line`, `origin`, `cause`, `remedy`, `evidence` fields.
3. If `TOOL.EXIT_NONZERO`, inspect `build/latest/<stage>.log` before changing the source.
4. If `VERIFY.MISMATCH`, use the saved input counterexample and execute `chipcompiler simulate ... --inputs '...'`. Gate `origin` traces point to source lines.
5. Reproduce with the exact project and `run_id` in `events.jsonl`; each clean run writes isolated timestamped stage events.
6. Use `chipcompiler diagnose` to generate a ZIP containing the report, event trace, input digests and tool discovery. Source files are opt-in.

Do not diagnose a `PIPELINE.BLOCKED` item as a router or compiler bug until its upstream prerequisite has passed. Do not infer a successful silicon build from DLS validity alone.

## Autosave and rollback

GUI saves modified buffers periodically, writes local zip snapshots and records a `dirty_session.flag` while open. Unexpected shutdown leaves a marker, and recovery buffers are kept at `.chipcompiler/unsaved`.

Snapshots are atomic ZIP replacements with manifests, retained for 30 revisions by default (configurable in the GUI). Files larger than 16 MiB and symbolic links are excluded **with explicit exclusion records** in snapshot manifests. Generated `build` data and `.git` are excluded. Restoring makes a pre-restore snapshot first. Restore requires explicit approval and checks for path traversal; it overlays recorded files and doesn't delete unrelated files.

The GUI attempts clean exit backups, but filesystem failures can still occur. Keep separate copies of irreplaceable project data.


## v0.5.0 clocked hierarchy diagnostics

- `MCD.CLOCK_PORT_COLLISION`: A user input named `clk` collides with the implicit clock needed by a registered top-level module or any stateful descendant. It is a source/interface error, **not** a physical clock-tree failure. Rename the data input; the generated Verilog supplies `clk` separately.
- `SOURCE.CONDITIONAL_STATE`: A branch contains `reg()` or a helper that transitively contains `reg()`. Speculatively lowering both branches would tick registers in an unselected branch, contrary to Python source semantics. Move state update outside the conditional, selecting the next value before calling `reg()`.
- `SOURCE.SHORTCIRCUIT_STATE`: A later operand of `and`/`or` can update hardware state. The existing purely Boolean lowering has no short-circuit enable protocol, so compilation is refused.
- `VERIFY.SAMPLING`: Sequential hierarchy checks execute deterministic test vectors, **not** a sequential formal proof. Keep the warning and trace files with the build.

When a source/mapping error occurs, dependent stages must remain `BLOCKED` with the original issue ID, not reported as independent errors.
