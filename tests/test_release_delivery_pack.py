from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from release_delivery_pack import (  # noqa: E402
    create_release_delivery_pack,
    verify_release_delivery_pack,
)
from prepublish_privacy_audit import REQUIRED_PRIVACY_CHECKS, create_privacy_audit  # noqa: E402
from rights_authorization_manifest import create_rights_authorization_report  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseDeliveryPackTests(unittest.TestCase):
    def _gate_reports(self, root: Path, video: Path, cover: Path, copy: Path) -> tuple[Path, Path]:
        privacy_manifest = root / "privacy-manifest.json"
        privacy_manifest.write_text(json.dumps({
            "schema_version": 1,
            "artifacts": {
                "source_video": {"path": video.name, "sha256": digest(video)},
                "final_video": {"path": video.name, "sha256": digest(video)},
                "cover": {"path": cover.name, "sha256": digest(cover)},
                "publishing_copy": {"path": copy.name, "sha256": digest(copy)},
            },
            "checks": [{
                "id": check, "status": "pass", "reviewer": "human",
                "reviewed_at": "2026-07-20T00:00:00Z", "evidence": ["reviewed"],
            } for check in REQUIRED_PRIVACY_CHECKS],
        }), encoding="utf-8")
        privacy = root / "privacy.json"
        create_privacy_audit(privacy_manifest, privacy)
        rights_manifest = root / "rights-manifest.json"
        rights_manifest.write_text(json.dumps({
            "schema_version": 1,
            "assets": [{
                "id": asset_id, "type": asset_type, "path": path.name,
                "sha256": digest(path), "status": "authorized", "rights_basis": "project_owned",
                "authorized_by": "producer", "authorized_at": "2026-07-20T00:00:00Z",
                "usage_scope": "publication",
            } for asset_id, asset_type, path in (
                ("video", "video", video),
                ("cover", "generated_image", cover),
                ("publishing-copy", "copy", copy),
            )],
        }), encoding="utf-8")
        rights = root / "rights.json"
        create_rights_authorization_report(rights_manifest, rights)
        return privacy, rights

    def test_pack_binds_exact_assets_and_never_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video, cover, copy = root / "video.mp4", root / "cover.png", root / "copy.json"
            video.write_bytes(b"video")
            cover.write_bytes(b"cover")
            copy.write_text('{"title":"Exact copy"}', encoding="utf-8")
            privacy, rights = self._gate_reports(root, video, cover, copy)
            authorization = root / "publication-authorization.json"
            authorization.write_text(json.dumps({
                "schema": "content-preserving-video-editor/publication-authorization",
                "schema_version": 1, "authorized": True, "authorized_by": "publisher",
                "authorized_at": "2026-07-20T00:00:00Z", "platform": "douyin",
                "publication_id": "pub-1", "bindings": {
                    "video_sha256": digest(video), "cover_sha256": digest(cover),
                    "copy_sha256": digest(copy)},
            }), encoding="utf-8")
            storyboard = root / "storyboard.json"
            storyboard.write_text(json.dumps({
                "events": [], "source": str(root / "private" / "source.mp4"),
            }), encoding="utf-8")
            pack = create_release_delivery_pack(
                video=video, cover=cover, publishing_copy=copy, privacy_audit=privacy,
                rights_report=rights, publication_authorization=authorization,
                output_dir=root / "delivery",
                additional_artifacts={"hyperframes_storyboard": storyboard},
                project_root=root,
            )
            self.assertEqual(pack["delivery_mode"], "local_only")
            self.assertFalse(pack["upload_performed"])
            self.assertEqual(pack["publication"]["id"], "pub-1")
            self.assertTrue((root / "delivery" / pack["artifacts"]["video"]["path"]).is_file())
            self.assertTrue((root / "delivery" /
                             pack["artifacts"]["hyperframes_storyboard"]["path"]).is_file())
            copied_storyboard = (root / "delivery" /
                                 pack["artifacts"]["hyperframes_storyboard"]["path"])
            self.assertNotIn(str(root), copied_storyboard.read_text(encoding="utf-8"))
            self.assertTrue(
                pack["artifacts"]["hyperframes_storyboard"]["absolute_paths_sanitized"]
            )
            self.assertEqual(verify_release_delivery_pack(
                root / "delivery", video=video, cover=cover, publishing_copy=copy,
                privacy_audit=privacy, rights_report=rights,
                publication_authorization=authorization,
            )["status"], "pass")
            original_storyboard = copied_storyboard.read_bytes()
            copied_storyboard.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash"):
                verify_release_delivery_pack(
                    root / "delivery", video=video, cover=cover, publishing_copy=copy,
                    privacy_audit=privacy, rights_report=rights,
                    publication_authorization=authorization,
                )

            copied_storyboard.write_bytes(original_storyboard)
            extra = root / "delivery" / "UNMANIFESTED_SECRET.txt"
            extra.write_text("secret", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unmanifested"):
                verify_release_delivery_pack(
                    root / "delivery", video=video, cover=cover, publishing_copy=copy,
                    privacy_audit=privacy, rights_report=rights,
                    publication_authorization=authorization,
                )

    def test_rights_report_must_cover_exact_video_cover_and_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video, cover, copy = root / "video.mp4", root / "cover.png", root / "copy.json"
            video.write_bytes(b"video")
            cover.write_bytes(b"cover")
            copy.write_text("{}", encoding="utf-8")
            privacy, rights = self._gate_reports(root, video, cover, copy)
            report = json.loads(rights.read_text(encoding="utf-8"))
            report["assets"] = report["assets"][1:]
            payload = {key: value for key, value in report.items()
                       if key not in {"schema", "schema_version", "payload_sha256"}}
            report["payload_sha256"] = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            rights.write_text(json.dumps(report), encoding="utf-8")
            authorization = root / "authorization.json"
            authorization.write_text(json.dumps({
                "schema": "content-preserving-video-editor/publication-authorization",
                "schema_version": 1, "authorized": True, "authorized_by": "publisher",
                "authorized_at": "2026-07-20T00:00:00Z", "platform": "douyin",
                "publication_id": "pub-1", "bindings": {
                    "video_sha256": digest(video), "cover_sha256": digest(cover),
                    "copy_sha256": digest(copy)},
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not cover"):
                create_release_delivery_pack(
                    video=video, cover=cover, publishing_copy=copy, privacy_audit=privacy,
                    rights_report=rights, publication_authorization=authorization,
                    output_dir=root / "delivery",
                )

    def test_missing_separate_authorization_or_binding_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = []
            for name in ("video.mp4", "cover.png", "copy.json", "privacy.json", "rights.json"):
                path = root / name
                path.write_bytes(b"x")
                files.append(path)
            with self.assertRaisesRegex(ValueError, "publication authorization"):
                create_release_delivery_pack(
                    video=files[0], cover=files[1], publishing_copy=files[2],
                    privacy_audit=files[3], rights_report=files[4],
                    publication_authorization=root / "missing.json", output_dir=root / "delivery",
                )
            authorization = root / "authorization.json"
            authorization.write_text(json.dumps({
                "schema": "content-preserving-video-editor/publication-authorization",
                "schema_version": 1, "authorized": True, "authorized_by": "publisher",
                "authorized_at": "2026-07-20T00:00:00Z", "platform": "douyin",
                "publication_id": "pub-1", "bindings": {
                    "video_sha256": "0" * 64, "cover_sha256": digest(files[1]),
                    "copy_sha256": digest(files[2])},
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bindings"):
                create_release_delivery_pack(
                    video=files[0], cover=files[1], publishing_copy=files[2],
                    privacy_audit=files[3], rights_report=files[4],
                    publication_authorization=authorization, output_dir=root / "delivery",
                )


if __name__ == "__main__":
    unittest.main()
