# Local candidate interchange, schema version 1

This is a file interface for optional future scoring/hook providers. The engine never
imports provider code, installs a model, opens a network connection or uploads footage.
It does not implement a local or Colab ML model. Rule-based ranking is always available.

Run automatic selection with `--analysis-only --export-candidates`. The run's
`exchange/candidates.json` contains at most 40 highest-ranked eligible candidates, with
three 480px-wide source frames for each of the first 20. Other candidates have metadata only.
Frame paths are relative to the exchange directory. No full candidate videos are exported.

```json
{
  "schema_version": 1,
  "run_id": "sha256 of source/settings/code signature",
  "source_sha256": "full source SHA-256",
  "candidates": [{
    "candidate_id": "24 hexadecimal characters",
    "start": 7.0,
    "end": 13.0,
    "duration": 6.0,
    "rule_score": 0.62,
    "features": {
      "motion_score": 0.8,
      "audio_score": 0.6,
      "opening_score": 0.5,
      "activity_contrast": 0.1,
      "sudden_change": 0.2,
      "quiet_interest": 0.1
    },
    "activity_pattern": "sustained",
    "suggested_editing": {"preset": "action", "confidence": 0.85, "reason": "Activity evidence"},
    "warnings": [],
    "boundary": {"semantic_payoff_verified": false, "dialogue_verified": false},
    "sampled_frames": [{"path": "candidate-id-0.jpg", "source_seconds": 7.0}]
  }]
}
```

Examples abbreviate hashes and optional fields; use the exact exported IDs. Candidate IDs
are derived from source checksum and microsecond-rounded source interval. The run ID also
binds settings/code. Component scores are heuristics, not calibrated probabilities. Additional
feature keys may be added without removing existing version-1 fields. Unknown activity
patterns should be handled as neutral by consumers. Times are source seconds with exclusive
out points. Frame-aligned rendering can differ by at most half a source frame at each bound.

A future local/Colab provider can read this structure and return a separate local JSON file:

```json
{
  "schema_version": 1,
  "run_id": "copy the exact exported run_id",
  "provider": "my-local-reranker-v1",
  "weight": 0.25,
  "scores": [{
    "candidate_id": "copy the exact candidate_id",
    "score": 0.8,
    "reason": "Optional provider evidence",
    "hook_suggestion": "Optional text for the creator to review"
  }]
}
```

Resume the exact analysis command with `--resume --rerank-file path/to/scores.json`.
Keep `--analysis-only` to inspect the new selection. Scores must be finite numbers in
[0,1], weight in [0,0.5] (default .25), and IDs unique and present in the exported shortlist.
The importer rejects wrong run IDs/schema, duplicate/unknown IDs, NaN/infinity/booleans,
unknown input fields and oversized/control-character text. Provider labels are limited
to 80 characters, reasons to 300 and hook suggestions to 120.

Combined score = `(1-weight) * rule_score + weight * external_score`. Candidates without
an imported score keep their rule score. Only already-qualified candidates can be reranked;
overlap/deduplication/diversity rules still apply. Original scores and external evidence remain
in candidate metadata and the HTML review report. No event labels or captions are applied.
The optional hook is a suggestion: copy/edit an accurate one into the review page's hook field
and use the normal review JSON export/import flow.

Rerank before manual review or rendering. Once decisions have been supplied or outputs exist,
changing the rerank file requires a fresh output directory. Repeating the same imported
document is idempotent. Its scores persist in the manifest on later resumes without the flag.
Changing source/settings/code requires a new exchange/run; never copy IDs across runs.

External transfer, provider inference and model setup remain outside the default engine and
under the user's control. Exported frames can contain private capture overlays; inspect them
before manually sharing them.
