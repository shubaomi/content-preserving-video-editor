# Content-Preserving Video Editor

This repository is the source of the preservation-first Director Skill. It
coordinates video-use, HyperFrames, FFmpeg, optional providers, human approvals,
QA, and one Universal MP4; it does not vendor or replace upstream Skills.

## Local setup

Use Python 3.11–3.13 and the compatible tools in
`references/environment-manifest.json`.

```powershell
python -m pip install -r requirements.txt
python scripts/director.py doctor --out doctor.json
python scripts/director.py init-project --root E:\Videos --video-id demo --source E:\input.mp4 --preset auto
python scripts/director.py preflight --project E:\Videos\demo\project.yaml --out preflight.json
python scripts/director.py run --project E:\Videos\demo\project.yaml --until sample_qa
python scripts/director.py next --project E:\Videos\demo\project.yaml
```

Doctor and preflight are read-only. Paid/provider, interactive review, event
cache, preference, feedback, audit, and release-pack paths are optional and
disabled by default. See `SKILL.md`, `references/config-schema.md`, and
`references/quality-gates.md` before enabling them.

`run --until sample_qa` means “advance toward the sample gate”; a new project
normally pauses first for real video-use transcript/EDL evidence, an LLM semantic
brief, or a HyperFrames project. This is an `action_required` handoff, not a
synthetic automatic result. Use `next` to see only the current owner, instruction,
expected output, and resume command. A stage marked `contract_ready` has policy
and requests but not yet a produced audio or cover asset.

## Validation

```powershell
python -m compileall -q scripts tests
python -m unittest discover -s tests -p "test_*.py"
python scripts/fixture_acceptance.py --fixtures tests/fixtures/acceptance-scenarios.json --out references/validation/six-fixture-acceptance.json
python scripts/current_golden_regression.py --fixtures tests/fixtures/acceptance-scenarios.json --policy tests/fixtures/current-golden-policy.json --out references/validation/current-golden-regression.json
```

Passing fixtures do not approve aesthetics, personal likeness, paid-provider
availability, real-platform performance, or publication. Those remain explicit
human/external gates.
