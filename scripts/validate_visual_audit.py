import argparse
import json
from pathlib import Path

REQUIRED = {"section_id", "start", "end", "chapter", "content_type", "current_visual", "score", "decision", "reason", "ip_role", "asset_type"}
DECISIONS = {"generate", "reuse_theme_asset", "ui_annotation", "caption_only", "none"}
INTEGRATION_MODES = {"pip-card", "masked-reveal", "split-panel", "character-cutout", "chapter-bridge"}
REDUNDANCY_ACTIONS = {"replace", "complement", "demote", "none"}

def validate(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    sections = data.get("sections", [])
    errors = []
    if not sections:
        errors.append("sections must contain at least one semantic chapter")
    for index, section in enumerate(sections):
        label = section.get("section_id", f"index-{index}")
        missing = sorted(REQUIRED - section.keys())
        if missing:
            errors.append(f"{label}: missing {', '.join(missing)}")
        if section.get("decision") not in DECISIONS:
            errors.append(f"{label}: unsupported decision {section.get('decision')!r}")
        if not str(section.get("reason", "")).strip():
            errors.append(f"{label}: decision reason is required")
        if section.get("decision") == "generate" and not section.get("confirmation_card"):
            errors.append(f"{label}: generate requires confirmation_card")
        if section.get("decision") == "generate" and section.get("asset_type") in (None, "", "none"):
            errors.append(f"{label}: generate requires a meaningful asset_type")
        if section.get("decision") in {"generate", "reuse_theme_asset"}:
            for field in ("semantic_owner", "relationship_to_existing_motion", "redundancy_action", "integration_mode", "background_treatment"):
                if not str(section.get(field, "")).strip():
                    errors.append(f"{label}: {section.get('decision')} requires {field}")
            if section.get("integration_mode") not in INTEGRATION_MODES:
                errors.append(f"{label}: unsupported integration_mode {section.get('integration_mode')!r}")
            if section.get("redundancy_action") not in REDUNDANCY_ACTIONS:
                errors.append(f"{label}: unsupported redundancy_action {section.get('redundancy_action')!r}")
    return {"ok": not errors, "sections": len(sections), "generate": sum(s.get("decision") == "generate" for s in sections), "errors": errors}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True, type=Path)
    result = validate(parser.parse_args().audit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
