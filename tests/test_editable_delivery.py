from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from editable_delivery import (  # noqa: E402
    EditableDeliveryError,
    build_editable_delivery,
    validate_editable_delivery,
)


class EditableDeliveryTests(unittest.TestCase):
    def _handoff(self, root: Path, *, partial: bool = False) -> Path:
        from editorial_projection import build_projection, project_semantics
        from editorial_handoff import build_handoff

        edl = {'source': 'cam', 'ranges': [{'start': 0, 'end': 4}]}
        projection = build_projection(
            baseline_edl=edl, candidate_edl=edl, fps=30,
            transcript={'words': [{'id': 1, 'text': '产品', 'start': 1, 'end': 2}]},
            input_hashes={k: '1' * 64 for k in ('source', 'transcript', 'base_edl', 'candidate_edl')})
        brief = project_semantics({'schema_version': 3, 'events': [
            {'id': 'proof', 'source_start': 1, 'source_end': 2, 'transcript_word_ids': [1]}]}, projection)
        captions = [{'start': 1, 'end': 1.5 if partial else 2, 'text': '产品'}]
        paths = {}
        for name, data in (('projection', projection), ('output_brief', brief), ('captions', captions)):
            path = root / f'{name}.json'
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            paths[name] = path
        bundle = build_handoff(**paths)
        target = root / 'instance-handoff.json'
        target.write_text(json.dumps(bundle, ensure_ascii=False), encoding='utf-8')
        return target

    def _inputs(self, root: Path) -> dict[str, Path]:
        automatic = root / "exports" / "final.mp4"
        candidate = root / "work" / "full-hyperframes.mp4"
        srt = root / "edit" / "master.srt"
        ass = root / "work" / "caption-treatment" / "master.ass"
        plan = root / "work" / "caption-treatment" / "plan.json"
        project = root / "hyperframes-full"
        for path, value in (
            (automatic, b"captioned-master"),
            (candidate, b"caption-free-candidate"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        srt.parent.mkdir(parents=True, exist_ok=True)
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")
        ass.parent.mkdir(parents=True, exist_ok=True)
        ass.write_text("[Script Info]\n[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,CaptionBase,,0,0,0,,字幕\n", encoding="utf-8")
        plan.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        project.mkdir(parents=True, exist_ok=True)
        (project / "index.html").write_text("<main data-composition-id='main'></main>", encoding="utf-8")
        (project / "storyboard.json").write_text(json.dumps({"events": []}), encoding="utf-8")
        return {
            "automatic_master": automatic,
            "caption_free_candidate": candidate,
            "caption_srt": srt,
            "caption_ass": ass,
            "caption_style_plan": plan,
            "hyperframes_project": project,
        }

    def test_builds_standard_repair_kit_with_editable_caption_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = self._inputs(root)
            manifest = build_editable_delivery(
                output_root=root / "work" / "director" / "editable-delivery",
                authorized_root=root,
                **inputs,
            )

            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ready")
            self.assertFalse(payload["interoperability"]["burned_master_text_editable"])
            self.assertFalse(payload["interoperability"]["native_editor_draft_generated"])
            self.assertEqual(Path(payload["captions"]["srt"]["path"]).name, "master.srt")
            self.assertEqual(Path(payload["captions"]["ass"]["path"]).name, "master.ass")
            self.assertEqual(validate_editable_delivery(manifest), [])

    def test_hash_drift_or_reusing_captioned_master_as_candidate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = self._inputs(root)
            with self.assertRaisesRegex(EditableDeliveryError, "distinct"):
                build_editable_delivery(
                    output_root=root / "work" / "director" / "editable-delivery",
                    authorized_root=root,
                    **{**inputs, "caption_free_candidate": inputs["automatic_master"]},
                )
            manifest = build_editable_delivery(
                output_root=root / "work" / "director" / "editable-delivery",
                authorized_root=root,
                **inputs,
            )
            Path(json.loads(manifest.read_text(encoding="utf-8"))["captions"]["srt"]["path"]).write_text(
                "changed", encoding="utf-8",
            )
            self.assertTrue(any("srt" in error and "stale" in error
                                for error in validate_editable_delivery(manifest)))

    def test_optional_instance_handoff_is_copied_and_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = self._inputs(root)
            source = self._handoff(root, partial=True)
            manifest = build_editable_delivery(output_root=root/'kit', authorized_root=root,
                                               instance_handoff=source, **inputs)
            payload = json.loads(manifest.read_text(encoding='utf-8'))
            record = payload['instance_handoff']
            self.assertEqual(record['source']['path'], str(source.resolve()))
            self.assertEqual(Path(record['path']).read_bytes(), source.read_bytes())
            self.assertEqual(record['caption_linkage_status'], 'partial')
            self.assertFalse(record['native_editor_verified'])
            self.assertEqual(validate_editable_delivery(manifest), [])

    def test_default_none_preserves_legacy_output_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = self._inputs(root)
            output = root/'kit'
            manifest = build_editable_delivery(output_root=output, authorized_root=root, **inputs)
            before = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
            build_editable_delivery(output_root=output, authorized_root=root, instance_handoff=None, **inputs)
            after = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertNotIn('instance_handoff', json.loads(manifest.read_text(encoding='utf-8')))

    def test_instance_handoff_copy_source_and_nested_drift_fail(self):
        for affected in ('copy', 'source', 'captions'):
            with self.subTest(affected=affected), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = self._handoff(root)
                manifest = build_editable_delivery(output_root=root/'kit', authorized_root=root,
                                                   instance_handoff=source, **self._inputs(root))
                payload = json.loads(manifest.read_text(encoding='utf-8'))
                path = {'copy': Path(payload['instance_handoff']['path']),
                        'source': source, 'captions': root/'captions.json'}[affected]
                path.write_text('{}', encoding='utf-8')
                self.assertTrue(validate_editable_delivery(manifest))

    def test_invalid_bundle_and_stale_nested_hash_rejected_before_copy(self):
        for fault in ('bundle_hash', 'nested', 'duplicate_key'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = self._handoff(root)
                if fault == 'nested':
                    (root/'captions.json').write_text('[]', encoding='utf-8')
                else:
                    data = json.loads(source.read_text(encoding='utf-8'))
                    data['bundle_sha256'] = '0' * 64
                    raw = json.dumps(data)
                    if fault == 'duplicate_key':
                        raw = raw[:-1] + ',"bundle_sha256":"0"}'
                    source.write_text(raw, encoding='utf-8')
                with self.assertRaises(EditableDeliveryError):
                    build_editable_delivery(output_root=root/'kit', authorized_root=root,
                                            instance_handoff=source, **self._inputs(root))
                self.assertFalse((root/'kit'/'editorial'/'instance-handoff.json').exists())

    def test_rehashed_changed_instances_do_not_override_bound_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._handoff(root)
            data = json.loads(source.read_text(encoding='utf-8'))
            data['semantic_instances'][0]['semantic_output_window']['start'] = 0
            data.pop('bundle_sha256')
            data['bundle_sha256'] = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                                             separators=(',', ':')).encode()).hexdigest()
            source.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(EditableDeliveryError, 'recomputed'):
                build_editable_delivery(output_root=root/'kit', authorized_root=root,
                                        instance_handoff=source, **self._inputs(root))

    def test_inline_integrity_is_not_upgraded_to_current_file_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._handoff(root)
            from editorial_handoff import build_handoff
            values = {name: json.loads((root/f'{name}.json').read_text(encoding='utf-8'))
                      for name in ('projection', 'output_brief', 'captions')}
            source.write_text(json.dumps(build_handoff(**values)), encoding='utf-8')
            manifest = build_editable_delivery(output_root=root/'kit', authorized_root=root,
                                               instance_handoff=source, **self._inputs(root))
            payload = json.loads(manifest.read_text(encoding='utf-8'))
            self.assertFalse(payload['instance_handoff']['file_inputs_recomputed'])
            self.assertEqual(payload['instance_handoff']['inline_integrity_only_inputs'],
                             ['captions', 'output_brief', 'projection'])
            self.assertEqual(validate_editable_delivery(manifest), [])

    def test_manifest_cannot_upgrade_partial_caption_linkage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._handoff(root, partial=True)
            manifest = build_editable_delivery(output_root=root/'kit', authorized_root=root,
                                               instance_handoff=source, **self._inputs(root))
            payload = json.loads(manifest.read_text(encoding='utf-8'))
            payload['instance_handoff']['caption_linkage_status'] = 'linked'
            manifest.write_text(json.dumps(payload), encoding='utf-8')
            self.assertTrue(any('claims' in error for error in validate_editable_delivery(manifest)))

    @unittest.skipUnless(os.name == "nt", "Windows Junction regression")
    def test_output_root_junction_cannot_escape_project(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside_temp:
            root = Path(temp)
            outside = Path(outside_temp)
            inputs = self._inputs(root)
            output = root / "work" / "director" / "editable-delivery"
            output.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(output), str(outside)],
                check=True, capture_output=True, text=True,
            )
            with self.assertRaises(EditableDeliveryError):
                build_editable_delivery(
                    output_root=output, authorized_root=root, **inputs,
                )
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
