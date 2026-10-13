"""Synthetic unit fixtures; no real-project parity or user approval claims."""
from pathlib import Path
import copy
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from director_contracts import write_json,sha256_file
from rendered_phase_parity import validate_pixel_parity,PROFILE_LIMITS


class RenderedPhaseParityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        ref=lambda p:{'path':str(p),'sha256':sha256_file(p)}
        self.ref=ref
        self.inputs={}
        for name in ('project_artifact','motion_design_contract','source_media'):
            path=self.root/(name+'.json');write_json(path,{'synthetic':True});self.inputs[name]=path
        write_json(self.inputs['project_artifact'],{'project_root':str(self.root),'synthetic':True})
        self.raw=self.root/'synthetic.mp4';self.raw.write_bytes(b'mock-decode-only')
        self.inputs['raw_render']=self.raw
        self.array=np.full((16,16,3),120,dtype=np.uint8)
        image=self.root/'pixels.png';Image.fromarray(self.array).save(image)
        phases=[{'phase':phase,'timestamp_seconds':frame/24,'snapshot':ref(image),
                 'actual_DOM_detail':{'source':{'x':0,'y':0,'width':16,'height':16}}}
                for phase,frame in zip(('entrance','mid','pre_exit','post_exit'),(0,1,2,3))]
        export=self.root/'export.json'
        write_json(export,{'project_artifact':ref(self.inputs['project_artifact']),
            'motion_design_contract_sha256':sha256_file(self.inputs['motion_design_contract']),
            'source_media_sha256':sha256_file(self.inputs['source_media']),
            'events':[{'event_id':'event','phases':phases}]})
        receipt=self.root/'receipt.json'
        write_json(receipt,{'event_id':'event','project_artifact':ref(self.inputs['project_artifact']),
            'input_hashes':{'motion_design_contract_sha256':sha256_file(self.inputs['motion_design_contract'])},
            'phase_observations':phases})
        self.receipts={'event':receipt}
        self.storyboard={'composition':{'fps':24,'width':16,'height':16},'events':[{'semantic_event_id':'event','editorial_recipe_id':'B02'}]}
        write_json(self.root/'storyboard.json',self.storyboard)
        self.report={'schema_version':2,'measurement_method':'same_frame_pixels_v1','status':'pass',
            'profile':'software_rgb_3_0035','limits':copy.deepcopy(PROFILE_LIMITS['software_rgb_3_0035']),
            'ssim_algorithm':'skimage_rgb_default_7x7',
            'inputs':{k:ref(v) for k,v in self.inputs.items() if k!='raw_render'},'renderer_export':ref(export),'raw_render':ref(self.raw),
            'fps':24,'source_area':[0,0,16,16],
            'samples':[{'event_id':'event','phase':p['phase'],'frame':i,'timestamp_seconds':p['timestamp_seconds'],
                'studio_snapshot':ref(image),'render_snapshot':ref(image),'keyframe_receipt':ref(receipt),
                'source_rgb_mae':0.,'source_fraction_any_channel_gt20':0.,'full_rgb_mae':0.,'full_rgb_ssim':1.}
                for i,p in enumerate(phases)]}
        self.decode=patch('rendered_phase_parity.decode_selected_frames',return_value={i:self.array.copy() for i in range(4)})
        self.decode.start();self.addCleanup(self.decode.stop)
        self.probe=patch('rendered_phase_parity.probe_render',return_value={'width':16,'height':16,'fps':24})
        self.probe.start();self.addCleanup(self.probe.stop)
        self.manifest_check=patch('rendered_phase_parity.validate_manifest',return_value=[])
        self.manifest_check.start();self.addCleanup(self.manifest_check.stop)

    def validate(self):
        return validate_pixel_parity(self.report,self.storyboard,self.inputs,self.receipts)

    def test_valid_bound_synthetic_fixture(self):self.assertEqual(self.validate(),[])
    def test_missing_phase(self):
        self.report['samples'].pop();self.assertTrue(self.validate())
    def test_wrong_integer_frame(self):
        self.report['samples'][1]['frame']=2;self.assertTrue(self.validate())
    def test_wrong_export_timestamp(self):
        self.report['samples'][1]['timestamp_seconds']=.5;self.assertTrue(self.validate())
    def test_stale_source_hash(self):
        self.report['inputs']['source_media']['sha256']='0'*64;self.assertTrue(self.validate())
    def test_stale_transitive_project_inventory(self):
        with patch('rendered_phase_parity.validate_manifest',return_value=['source file stale']):
            self.assertTrue(self.validate())
    def test_stale_export(self):
        Path(self.report['renderer_export']['path']).write_text('{}');self.assertTrue(self.validate())
    def test_stale_receipt(self):
        self.report['samples'][0]['keyframe_receipt']['sha256']='0'*64;self.assertTrue(self.validate())
    def test_relaxed_limits_rejected(self):
        self.report['limits']['source_rgb_mae_max']=30;self.assertTrue(self.validate())
    def test_fabricated_metrics_rejected(self):
        self.report['samples'][0]['source_rgb_mae']=2;self.assertTrue(self.validate())
    def test_render_png_not_from_selected_raw_frame(self):
        with patch('rendered_phase_parity.decode_selected_frames',return_value={i:np.zeros_like(self.array) for i in range(4)}):
            self.assertTrue(self.validate())
    def test_shrunk_source_area_rejected(self):
        self.report['source_area']=[0,0,1,1];self.assertTrue(self.validate())
    def test_metric_failure_cannot_use_pass_flag(self):
        image=self.root/'wrong.png';Image.fromarray(np.full_like(self.array,150)).save(image)
        for sample in self.report['samples']:sample['render_snapshot']=self.ref(image)
        self.assertTrue(self.validate())
    def test_portrait_uses_fixed_095_profile(self):
        self.report['profile']='portrait_ssim_095';self.report['limits']=copy.deepcopy(PROFILE_LIMITS['portrait_ssim_095'])
        self.report['ssim_algorithm']='ffmpeg_ssim_all_rgb'
        self.storyboard['events'][0]['editorial_recipe_id']='A01'
        write_json(self.root/'storyboard.json',self.storyboard)
        with patch('rendered_phase_parity.ffmpeg_ssim',return_value=1.):self.assertEqual(self.validate(),[])
    def test_software_cannot_select_looser_portrait_profile(self):
        self.report['profile']='portrait_ssim_095';self.report['limits']=copy.deepcopy(PROFILE_LIMITS['portrait_ssim_095'])
        self.report['ssim_algorithm']='ffmpeg_ssim_all_rgb'
        self.assertTrue(self.validate())
    def test_forged_caller_storyboard_family_rejected(self):
        self.storyboard['events'][0]['editorial_recipe_id']='A01'
        self.report['profile']='portrait_ssim_095';self.report['limits']=copy.deepcopy(PROFILE_LIMITS['portrait_ssim_095'])
        self.report['ssim_algorithm']='ffmpeg_ssim_all_rgb'
        self.assertTrue(self.validate())
    def test_missing_caller_bound_render_fails(self):
        self.inputs.pop('raw_render');self.assertTrue(self.validate())
    def test_portrait_different_ssim_algorithm_rejected(self):
        self.report['profile']='portrait_ssim_095';self.report['limits']=copy.deepcopy(PROFILE_LIMITS['portrait_ssim_095'])
        self.assertTrue(self.validate())
    def test_raw_video_fps_cannot_be_faked(self):
        with patch('rendered_phase_parity.probe_render',return_value={'width':16,'height':16,'fps':30}):
            self.assertTrue(self.validate())
    def test_unknown_profile(self):
        self.report['profile']='best_offset';self.assertTrue(self.validate())
    def test_decode_failure_is_error(self):
        with patch('rendered_phase_parity.decode_selected_frames',side_effect=ValueError('decode failed')):
            self.assertTrue(self.validate())


if __name__=='__main__':unittest.main()
