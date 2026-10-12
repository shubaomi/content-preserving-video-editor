"""Production Director gates with synthetic local facts; no user media/render."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from director import Director
from director_contracts import DirectorContractError, sha256_file, write_json
import motion_editorial as me

APPROVAL = ROOT / "references/motion-editorial-v3-validation/20261012-wp3/approval-receipt.json"


class MotionEditorialDirectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"synthetic fixture media; never rendered")

    def director(self, enabled=True, opening="propose_only"):
        config = {"schema_version": 15, "video_id": "editorial-fixture",
            "paths": {"root": str(self.root), "work": "work", "edit": "edit", "exports": "exports"},
            "source": {"primary_video": str(self.source), "input_mode": "existing_edit_polish", "content_type": "screen_tutorial"},
            "identity": {"mode": "third_party"}, "motion_quality": {"enabled": True},
            "motion_editorial": {"enabled": enabled, "direction": "professional_software_demo",
                "design_approval_path": str(APPROVAL), "opening": opening,
                "hook_approval_path": "not-used-short-hook.json" if opening == "approved_duplicate" else None}}
        project = self.root / "project.yaml"
        project.write_text(yaml.safe_dump(config), encoding="utf-8")
        return Director(project)

    def authorities(self, director):
        transcript = director.video_use_dir / "transcripts/source.json"
        words = [{"id": "w1", "type": "word", "text": "产品演示", "start": 0, "end": 1}]
        write_json(transcript, {"words": words})
        write_json(director.video_use_dir / "edl.json", {"owner": "video-use",
            "sources": {"cam": str(self.source)}, "ranges": [
                {"source": "cam", "segment_id": "body", "start": 0, "end": 4}]})
        write_json(director.video_use_dir / "captions.json", {"segments": [
            {"start": 0, "end": 1, "text": "产品演示"}]})
        frame = director.root / "evidence/frame.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        # This fixture only exercises evidence binding, not image-quality claims.
        frame.write_bytes(b"synthetic-frame-reference")
        write_json(director.evidence_bundle_path, {"duration_seconds": 4,
            "ffprobe": {"streams": [{"codec_type": "video", "avg_frame_rate": "30/1"}]},
            "display": {"width": 1920, "height": 1080, "orientation": "landscape"},
            "transcript": {"sha256": sha256_file(transcript), "term_evidence": [
                {"word_id": w["id"], "text": w["text"], "start": w["start"], "end": w["end"]} for w in words]},
            "representative_frames": [{"path": str(frame), "sha256": sha256_file(frame)}]})
        brief = {"schema_version": 3, "opportunity_model": "decision_complete_v1",
            "generated_by": "synthetic-test-llm", "content_reading": "raw_word_transcript_and_evidence_frames",
            "transcript_sha256": sha256_file(transcript), "evidence_bundle_sha256": sha256_file(director.evidence_bundle_path),
            "evidence_frames": [str(frame)], "opening_hook": {"status": "not_selected", "evidence": ["direct fixture"]},
            "events": [{"id": "e1", "decision": "reuse_source", "decision_rationale": "Actual action remains primary",
                "source_start": 0, "source_end": 1, "output_start": 0, "output_end": 1,
                "anchor": "产品演示", "transcript_quote": "产品演示", "transcript_word_ids": ["w1"],
                "viewer_takeaway": "产品演示", "target_frame_evidence": [str(frame)]}]}
        source_brief = director.root / "semantic-brief.json"
        write_json(source_brief, brief)
        write_json(director.adaptive_layout_path, {"schema_version": "1.0.0", "status": "resolved",
            "constraints": {}, "fallback": None, "guessed_coordinates_allowed": False})
        write_json(director.root / "brand-motion/brand-motion-playbook.json", {"status": "synthetic fixture"})
        return transcript, source_brief

    def test_default_off_creates_no_motion_editorial_sidecars(self):
        director = self.director(False)
        self.assertEqual(director._prepare_editorial_projection("sample"), [])
        self.assertFalse((director.root / "motion-editorial").exists())
        self.assertEqual(len(director.state["stages"]), 19)

    def test_known_style_receipt_current_and_covers_direction(self):
        self.assertTrue(APPROVAL.is_file())
        self.assertEqual(sha256_file(APPROVAL), me.DESIGN_APPROVAL_SHA256)
        self.assertEqual(me.validate_design_approval(APPROVAL, "professional_software_demo")["candidate_id"], "motion-editorial-v3-20261012")

    def test_semantic_then_production_builds_v4_without_changing_source(self):
        director = self.director()
        transcript, source_brief = self.authorities(director)
        before = {path: path.read_bytes() for path in (self.source, transcript, source_brief, director.video_use_dir / "edl.json")}
        director._start("semantic_brief")
        director.stage_semantic_brief()
        self.assertEqual(director.state["stages"]["semantic_brief"]["status"], "complete")
        director._start("production_contract")
        director.stage_production_contract()
        self.assertEqual(director.state["stages"]["production_contract"]["status"], "complete")
        projection = me.load(director.root / "motion-editorial/timeline-projection.json")
        self.assertEqual(projection["mode"], "preserve_order")
        self.assertNotIn("hook_approval", projection)
        projected_path = director.root / "motion-editorial/sample-output-semantic-v4.json"
        projected = me.load(projected_path)
        self.assertEqual(projected["schema_version"], 4)
        self.assertEqual(projected["events"][0]["id"], "e1@body")
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        contract = me.load(director.production_contract_path)
        self.assertEqual(contract["inputs"]["semantic_brief"]["sha256"], sha256_file(projected_path))

    def test_missing_shot_plan_is_action_required_not_generic_fallback(self):
        director = self.director()
        self.authorities(director)
        director._start("production_contract")
        director.stage_production_contract()
        director._start("hyperframes_storyboard")
        with self.assertRaisesRegex(DirectorContractError, "shot plan"):
            director._ensure_motion_design(scope="sample", brief_path=director.semantic_brief_path,
                                           binding_dir=director.sample_target_binding_dir)
        self.assertEqual(director.state["stages"]["hyperframes_storyboard"]["status"], "action_required")
        request = me.load(director.root / "motion-editorial/sample-shot-plan-request.json")
        self.assertFalse(request["default_decorations"])
        self.assertFalse(request["selection_by_quota"])

    def test_current_edl_source_mismatch_blocks_projection(self):
        director = self.director()
        self.authorities(director)
        edl_path = director.video_use_dir / "edl.json"
        edl = me.load(edl_path)
        edl["sources"]["cam"] = str(self.root / "different.mp4")
        write_json(edl_path, edl)
        director._start("production_contract")
        with self.assertRaisesRegex(DirectorContractError, "source file differs"):
            director.stage_production_contract()
        self.assertEqual(director.state["stages"]["production_contract"]["status"], "action_required")

    def test_stale_style_receipt_blocks_production_without_new_authority(self):
        director = self.director()
        self.authorities(director)
        changed = self.root / "changed-style.json"
        changed.write_bytes(APPROVAL.read_bytes() + b" ")
        director.project["motion_editorial"]["design_approval_path"] = str(changed)
        director._start("production_contract")
        with self.assertRaisesRegex(DirectorContractError, "approved design receipt required"):
            director.stage_production_contract()
        self.assertEqual(director.state["stages"]["production_contract"]["status"], "action_required")
        self.assertFalse(director.production_contract_path.exists())

    def test_opening_purpose_preserve_order_is_blocked(self):
        director = self.director()
        self.authorities(director)
        director._start("production_contract")
        director.stage_production_contract()
        projection = me.load(director.root / "motion-editorial/timeline-projection.json")
        write_json(director.root / "motion-editorial/sample-validation-plan.json", {
            "purpose": "opening_edit", "output_start": 0,
            "full_render_authorized": False, "projection_sha256": me.digest(projection)})
        director._start("sample_qa")
        with self.assertRaisesRegex(DirectorContractError, "opening_edit requires approved_duplicate"):
            director.stage_sample_qa()
        self.assertEqual(director.state["stages"]["sample_qa"]["status"], "action_required")

    def test_short_hook_scope_never_authorizes_full_storyboard(self):
        director = self.director(opening="approved_duplicate")
        director._start("full_hyperframes_storyboard")
        with self.assertRaisesRegex(DirectorContractError, "short_preview only"):
            director.stage_full_hyperframes_storyboard()
        self.assertEqual(director.state["stages"]["full_hyperframes_storyboard"]["status"], "action_required")

    def test_caption_configuration_resume_keeps_source_chain_and_costs(self):
        director = self.director()
        transcript, _ = self.authorities(director)
        director._complete("inspect", [self.source])
        director.stage_provider_governance()
        director._complete("video_use_timeline", [transcript, director.video_use_dir / "edl.json"])
        old_ledger = me.load(director.root / "cost-ledger.json")
        project = self.root / "project.yaml"
        config = yaml.safe_load(project.read_text(encoding="utf-8"))
        config.setdefault("editing", {})["caption_treatment"] = {"base_color": "#FFFFFF"}
        project.write_text(yaml.safe_dump(config), encoding="utf-8")
        resumed = Director(project)
        self.assertEqual(resumed.state["stages"]["inspect"]["status"], "complete")
        self.assertEqual(resumed.state["stages"]["video_use_timeline"]["status"], "complete")
        self.assertEqual(me.load(resumed.root / "cost-ledger.json")["totals"], old_ledger["totals"])
        resumed._validate_provider_governance()

    def test_handoff_is_current_and_does_not_claim_native_editor_acceptance(self):
        director = self.director()
        self.authorities(director)
        director._start("production_contract")
        director.stage_production_contract()
        artifacts = director._write_editorial_instance_handoff("sample")
        bundle = me.load(artifacts[0])
        self.assertFalse(bundle["native_editor_verified"])
        self.assertEqual(bundle["semantic_instances"][0]["semantic_event_id"], "e1@body")

    def test_visual_only_render_passes_source_projection_mqe_and_shot_chain(self):
        from director_contracts import REQUIRED_VISUAL_FIELDS, validate_semantic_brief
        director = self.director()
        _, source_brief = self.authorities(director)
        brief = me.load(source_brief)
        event = brief['events'][0]
        event.update(decision='render', approved_visible_copy=['产品演示'],
            editorial_copy_policy='source_only', semantic_role='explain', form='camera_focus',
            relevance_rationale='Inspect real operation', viewer_job='See product detail',
            visual_mechanism='Real source crop', protected_zones=['captions'],
            placement='source', size='measured', background='source', read_time=1,
            motion={phase:'bounded source camera' for phase in ('entrance','reveal','hold','exit')},
            audio_decision={'type':'intentionally_silent','reason':'speech first'},
            deduplication='No duplicate label', visual_structure={field:'real source camera' for field in REQUIRED_VISUAL_FIELDS})
        write_json(source_brief,brief)
        director._start('production_contract')
        director.stage_production_contract()
        projected = me.load(director.semantic_brief_path)
        self.assertEqual(projected['events'][0]['approved_visible_copy'], [])
        invalid = me.load(source_brief)
        invalid['events'][0]['approved_visible_copy'] = []
        self.assertTrue(any('approved_visible_copy' in error for error in validate_semantic_brief(invalid)))
        projection = me.load(director.root/'motion-editorial/timeline-projection.json')
        frame = Path(event['target_frame_evidence'][0])
        shot = {'instance_id':'e1@body','decision':'shot','recipe_id':'B01',
            'viewer_task':'Inspect real operation','information_gain':'Detail','primary_focus':'product',
            'rationale':'No additional label needed','source_crop':{'x':.1,'y':.1,'width':.8,'height':.8},
            'source_box':{'x':0,'y':0,'width':960,'height':540},'approved_visible_copy':[],
            'phases':{phase:{'start':i*.25,'end':(i+1)*.25} for i,phase in enumerate(('entrance','explain','hold','exit'))},
            'evidence':{'frame_refs':[me.ref(frame)],'maximum_scale':2},
            'sound':{'decision':'intentionally_silent','reason':'speech first'},'output_start':0,'output_end':1}
        plan = {'schema_version':2,'kind':'shot_motion_plan','direction':'professional_software_demo',
            'projection_sha256':me.digest(projection),'semantic_sha256':me.digest(projected),
            'default_decorations':False,'events':[shot]}
        write_json(director.root/'motion-editorial/sample-shot-motion-plan.json',plan)
        director._start('hyperframes_storyboard')
        contract, _ = director._ensure_motion_design(scope='sample', brief_path=director.semantic_brief_path,
                                                    binding_dir=director.sample_target_binding_dir)
        self.assertEqual(contract['opportunities'][0]['approved_visible_copy'], [])
        payload = me.load(director.motion_design_dir('sample')/'editorial-renderer-payload.json')
        from director_contracts import STORYBOARD_SEMANTIC_FIELDS, STORYBOARD_SEMANTIC_TIME_FIELDS, validate_storyboard_semantic_binding
        from motion_contracts import validate_storyboard_motion_binding
        projected_event = projected['events'][0]
        rendered = {field:projected_event[field] for field in (*STORYBOARD_SEMANTIC_FIELDS,
            *STORYBOARD_SEMANTIC_TIME_FIELDS,'target_frame_evidence','relevance_rationale','visual_mechanism','approved_visible_copy')}
        opportunity = contract['opportunities'][0]
        rendered.update(id='shot-1',semantic_event_id='e1@body',editorial_instance_id='e1@body',
            editorial_plan_sha256=payload['plan_sha256'],editorial_recipe_id='B01',visible_copy_manifest=[],
            motion_design_contract_id=contract['contract_id'],recipe_id=opportunity['recipe_id'],
            target_binding_ids=opportunity['target_binding_ids'])
        from motion_quality_engine import choreography_fingerprint
        from motion_contracts import load_recipe_registry
        recipe = next(row for row in load_recipe_registry()['recipes'] if row['recipe_id'] == opportunity['recipe_id'])
        rendered['choreography_fingerprint_sha256'] = choreography_fingerprint(recipe)
        storyboard = {'events':[rendered]}
        self.assertEqual(validate_storyboard_semantic_binding(storyboard,projected),[])
        self.assertEqual(validate_storyboard_motion_binding(storyboard,contract),[])
        self.assertEqual(me.validate_storyboard_binding(storyboard,payload),[])
        rendered['editorial_instance_id'] = 'wrong@body'
        self.assertTrue(validate_storyboard_semantic_binding(storyboard,projected))
        rendered['editorial_instance_id'] = 'e1@body'
        shot['recipe_id'] = 'B02'
        with self.assertRaisesRegex(ValueError,'source_only'):
            me.compile_shot_plan(plan,projection=projection,output_brief=projected,
                                 direction='professional_software_demo',roots=[self.root])
        # The same actual source→production→MQE path also supports A01 with no label.
        project = self.root/'project.yaml'
        config = yaml.safe_load(project.read_text(encoding='utf-8'))
        config['identity']['mode'] = 'self'
        config['source']['content_type'] = 'talking_head'
        config['motion_editorial']['direction'] = 'authentic_product_editorial'
        project.write_text(yaml.safe_dump(config),encoding='utf-8')
        director = Director(project)
        director._start('production_contract')
        director.stage_production_contract()
        plan['direction'] = 'authentic_product_editorial'
        shot['recipe_id'] = 'A01'
        write_json(director.root/'motion-editorial/sample-shot-motion-plan.json',plan)
        director._start('hyperframes_storyboard')
        contract, _ = director._ensure_motion_design(scope='sample', brief_path=director.semantic_brief_path,
                                                    binding_dir=director.sample_target_binding_dir)
        self.assertEqual(contract['opportunities'][0]['approved_visible_copy'], [])


if __name__ == "__main__":
    unittest.main()
