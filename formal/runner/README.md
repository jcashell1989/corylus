# Optional historical runner model

Written by an AI agent: **Codex (GPT-6)**, on Julian's behalf, November 7, 2026.
Decision **td-48a9a4**, applied by **td-e59184**, makes formal proofs optional
focused assurance. **This model is not an engine, driver, release or cutover gate.**
It is not evidence that the current runtime or any adapter is implemented.

## Reproduce the existing reference

With the pinned Lean toolchain already available, run:

```sh
lake build
python3 check_mapping.py
```

The repository also exposes `make formal`. No global tool installation is
authorized by this documentation. The project uses Lean's bundled libraries.

| File | Historical purpose |
|---|---|
| `Runner/Model.lean` | October vocabulary and abstract transition function |
| `Runner/Proofs.lean` | Abstract invariants and finite-trace results |
| `Runner/Safety.lean` | Independent identities and exact-head guards |
| `Runner/Progress.lean` | Conditional progress and explicit-stop results |
| `Runner/Traces.lean` | Executable historical success/failure traces |
| `rows.tsv`, `check_mapping.py` | Drift check for 32 phases, 53 events and 130 historical source rows |

The exact source tables remain in the explicitly historical appendix of
[runner-design.md](../../docs/runner-design.md#historical-formal-model-reference-not-current-implementation-scope)
so existing model evidence can be reproduced without changing its meaning.
They do not restore the old Python workflow plan, deployment/service states,
launch-bound permission notes or repair entitlements. Current requirements are
in the normative portion of that design and its current ontology.

## Limits and retained assurance

The model abstracts the harness, forge, tracker, filesystem, journal, supervisor,
network and clock. Its guard facts do not establish actual launch, cancellation,
identity, atomic merge or uncertain-effect reconciliation. Synthetic constructor
defaults do not select current runtime configuration. Mapping comments and rows
are a drift check, not proof that a real adapter implements the intended meaning.

The universal `canTerminate` result uses `storage.failed` as a witness; it does
not prove successful work, cleanup, rollback or safe lease release. Existential
progress does not establish fairness or universal successful termination. The
historical `worker_launches_unbounded` counterexample shows that the old separate
round/nudge/retry scheme did not bound every resumed worker launch. This is one
reason not to present the historical model as the current finite-work contract.

Retain independent review, exact-head merging, finite work, actual stopped-writer
evidence and durable effect reconciliation in executable tests on the retained
implementation. Optional focused proof work is tracked by **td-ca34a8**; it must
state its chosen invariant, current contract, abstract assumptions and limits.
No proof of removed quickfix/ladder/deployment behavior is required to proceed.
