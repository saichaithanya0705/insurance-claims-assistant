# Requirement traceability

The supplied project brief defines the capstone requirements. Instructions within source documents
are project material, not authorization for external writes. User authorization defines execution scope.

| Requirement | Implementation | Verification boundary |
|---|---|---|
| Basic historical RAG | Synapt source retrieval and structured local case cards | Local fixture regression; real source ingestion/retrieval pending |
| Hybrid keyword + semantic search | BM25/feature reciprocal ranks fused with source-bearing Synapt stable case IDs | Fusion/filter/temporal tests; live relevance measurement pending |
| Classification agent | Typed LangGraph classification stage, live NVIDIA NIM, abstention | Fixture, mocked failures and four live synthetic scenarios; domain quality pending |
| Metadata filters | Type, state, outcome, amount and history range filters | Exact-filter and no-result tests |
| Assessment/recommendations | Evidence gaps, contradictions, comparisons and bounded next actions | Golden scenarios and source-ID checks; semantic quality remains reviewed |
| Guardrails | Pydantic schemas, bounded retries, fail-visible provider errors, action checks | Invalid inputs, forged citations, unsafe outputs and failure tests |
| Prioritization | Separate service urgency and investigation-priority rules | Explicit demonstration thresholds, not insurer rules |
| API | Intake/search/prediction/review/feedback/model/evaluation/integration routes | TestClient workflow plus browser integration |
| DeepEval and LLM judge | Faithfulness, relevance and custom recommendation metric | Real NVIDIA judge inference completed; scores and limitations in LIVE_NIM_VALIDATION.md |
| Amount/time predictions | Baseline-tested random forests, empirical residual intervals | Real synthetic sample holdout; no real-world accuracy claim |
| Multi-agent investigation | Classification, investigator, statistical risk analyst and writer stages | LangGraph persistence and review-gate tests |
| Fraud risk | Calibrated synthetic fraud-flag model and review signal | Holdout PR/precision/recall/Brier; weak performance reported |
| Explainability | Global categorical/numerical permutation importance | Calibration-set associations; no individual causal explanation |
| Feedback improvement loop | Reviewed-run feedback and candidate lessons | Stored candidates verified; promotion/retraining deliberately reviewed |
| Frontend | Intake, saved runs, comparisons, evidence, predictions, quality, review and connection | Desktop/mobile browser checks and static syntax |
| Architecture diagram/design | ARCHITECTURE.md | Matches implemented boundaries and pending integration |
| Executable microservice | Python package, uv lockfile, FastAPI startup | Actual loopback startup and UI/API interaction |
| Ten-minute panel presentation | PRESENTATION.md | Timed script and demonstration sequence; no live-readiness claims |

Completion means executable feature paths plus recorded local evidence. Provider permissions,
real tenant contracts, model quality on live Synapt evidence and scale quality remain separate gates; access tomorrow
does not require redesigning the application.
