"""QA-A does not turn general clipping into an allowed condition."""
import sys
import unittest
import tempfile
from unittest.mock import patch
from copy import deepcopy
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from source_reframe_evidence import expected_camera_rect, validate_camera_geometry, validate_source_reframe_phase
from director_contracts import read_json, write_json, sha256_file
from motion_editorial import digest


class SourceReframeGeometryTests(unittest.TestCase):
    def setUp(self):
        self.shot = dict(recipe_id='A01', decision='shot', output_start=1, output_end=5,
            source_crop=dict(x=.02, y=.05, width=.95, height=.95),
            source_box=dict(x=30, y=0, width=480, height=840),
            phases=dict(explain=dict(start=.2, end=1), exit=dict(start=3, end=3.9)))
        rect = expected_camera_rect(self.shot, 3)
        self.observed = dict(source_rect=rect, matrix=[1/.95,0,0,1/.95,-.02*480/.95,-.05*840/.95],
            transform_origin=[0,0], added_paint=[], visible=True)
        self.regions = [dict(x=.2,y=.1,width=.6,height=.8)]

    def test_background_crop_is_allowed_with_intact_subject(self):
        self.assertLess(self.observed['source_rect']['y'], 0)
        self.assertEqual(validate_camera_geometry(self.shot, 3, self.observed,
            self.regions, width=540, height=960, caption_top=868), [])

    def test_each_missing_lost_or_cropped_protection_fails(self):
        for regions in ([], [None], [dict(x=0,y=0,width=1,height=1)]):
            with self.subTest(regions=regions):
                self.assertTrue(validate_camera_geometry(self.shot, 3, self.observed,
                    regions, width=540, height=960, caption_top=868))

    def test_added_graphic_is_never_source_crop(self):
        observed = deepcopy(self.observed)
        observed['added_paint'] = [dict(x=-2,y=0,width=20,height=20)]
        self.assertTrue(validate_camera_geometry(self.shot, 3, observed,
            self.regions, width=540, height=960, caption_top=868))

    def test_wrong_matrix_rect_origin_and_unknown_fail(self):
        for field,value in [('matrix',[1,0,0,1,0,0]),('source_rect',{}),
                            ('transform_origin',[1,0]),('visible',False),('matrix',None)]:
            observed = {**self.observed,field:value}
            self.assertTrue(validate_camera_geometry(self.shot,3,observed,
                self.regions,width=540,height=960,caption_top=868))

    def test_caption_intrusion_is_rejected(self):
        self.assertTrue(validate_camera_geometry(self.shot,3,self.observed,
            self.regions,width=540,height=960,caption_top=600))

    def test_non_camera_and_outside_event_fail(self):
        self.assertTrue(validate_camera_geometry({**self.shot,'recipe_id':'A02'},3,
            self.observed,self.regions,width=540,height=960,caption_top=868))
        self.assertTrue(validate_camera_geometry(self.shot,8,self.observed,
            self.regions,width=540,height=960,caption_top=868))


class SourceReframeBindingTests(SourceReframeGeometryTests):
    def setUp(self):
        super().setUp()
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'source').mkdir()
        self.source=self.root/'source/video.mp4'
        self.source.write_bytes(b'unit fixture; not real-media validation')
        self.project=self.root/'renderer-project-manifest.json'
        self.contract=self.root/'motion.json'
        write_json(self.project,{})
        write_json(self.root/'storyboard.json',dict(composition=dict(width=540,height=960)))
        self.projection=dict(input_hashes=dict(source=sha256_file(self.source)),
            segments=[dict(output_start=1,output_end=5,source_range=dict(start=1,end=5),speed=1)])
        self.brief={}
        self.shot['instance_id']='event'
        plan=dict(events=[self.shot],direction='authentic_product_editorial',
            projection_sha256=digest(self.projection),semantic_sha256=digest(self.brief))
        frames=[]
        for i,time in enumerate([1,3,5]):
            file=self.root/f'{i}.png'
            Image.new('RGB',(40,60),(i*60,0,0)).save(file)
            frames.append({**self.ref(file),'timestamp_seconds':time})
        self.display=dict(width=720,height=1280,rotation_degrees=0)
        def review(kinds):
            return dict(schema_version=2,kind='protected_region_evidence',source=self.ref(self.source),
                display=self.display,coordinate_space='normalized_display_v1',
                provenance=dict(method='manual_visual_review',reviewer='unit',reviewed_at='2026-10-13'),
                required_region_types=kinds,observations={kind:[dict(region_id=kind,status='present',
                    source_start=1,source_end=5,bbox=self.regions[0],geometry_method='bounded_review_envelope',
                    evidence=frames)] for kind in kinds})
        data=dict(shot_plan=plan,projection=self.projection,semantic_brief=self.brief,
            protected_review=review(['faces','hands']),product_review=review(['products']),
            caption_plan=dict(treatment=dict(max_scale_percent=112,layout=dict(single_line=True,font_size_px=28,margin_bottom_px=24))),
            plan_approval=dict(kind='explicit_user_plan_and_bounded_sample_authorization',approved_by='unit',user_message='fixture only',
                restrictions=dict(full_render_authorized=False),documents=[],
                source_bindings=[dict(id='A',bindings=[self.ref(self.source)])],
                authorized_samples=[dict(id='A',source_range_seconds=[1,5])]))
        self.inputs=dict(project_artifact=self.ref(self.project),source_media=self.ref(self.source),media_asset=self.ref(self.source))
        for name,value in data.items():
            file=self.root/(name+'.json');write_json(file,value);self.inputs[name]=self.ref(file)
        write_json(self.contract,dict(source_media=self.ref(self.source),opportunities=[dict(semantic_event_id='event',output_window=dict(start_seconds=1,end_seconds=5))]))
        self.inputs['motion_contract']=self.ref(self.contract)
        self.intent=dict(schema_version=1,kind='source_reframe_intent',inputs=self.inputs,
            display=self.display,canvas=dict(width=540,height=960),caption_top=868,event_sources=dict(event='#video'))
        self.phase=dict(timestamp_seconds=3,visible_text=[],source_reframe_observation={**self.observed,
            'selector':'#video','source_asset':self.ref(self.source),'canvas':dict(width=540,height=960),'caption_top':868})

    def ref(self,path):
        return dict(path=str(path.resolve()),sha256=sha256_file(path))

    def validate(self):
        path=self.root/'intent.json';write_json(path,self.intent)
        # Compiler validation has its own contract suite; this suite exercises
        # real nested file/image/protection readers around its interface.
        with patch('source_reframe_evidence.compile_shot_plan',return_value={}):
            return validate_source_reframe_phase(self.ref(path),phase=self.phase,event_id='event',
                project_artifact=self.project,motion_contract_path=self.contract)

    def test_current_bound_phase(self):
        self.assertEqual(self.validate(),[])

    def test_source_and_plan_hash_drift(self):
        for key in ('source_media','shot_plan','projection','protected_review','product_review'):
            old=self.inputs[key]['sha256'];self.inputs[key]['sha256']='0'*64
            self.assertTrue(self.validate(),key);self.inputs[key]['sha256']=old

    def test_product_unknown_gap_and_single_frame(self):
        path=Path(self.inputs['product_review']['path']);original=read_json(path)
        for mutation in ('unknown','gap','one_frame'):
            value=deepcopy(original);row=value['observations']['products'][0]
            if mutation=='unknown':row['status']='unknown';row.pop('bbox')
            elif mutation=='gap':row['source_end']=2.9
            else:row['evidence']=row['evidence'][:1]
            write_json(path,value);self.inputs['product_review']=self.ref(path)
            self.assertTrue(self.validate(),mutation)

    def test_inflated_canvas_and_weakened_caption_lane(self):
        self.intent['canvas']['height']=1000
        self.assertTrue(self.validate())
        self.intent['canvas']['height']=960
        self.intent['caption_top']=950
        self.phase['source_reframe_observation']['caption_top']=950
        self.assertTrue(self.validate())
