"""QA-C contract fixtures, not claims of real browser/render execution."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import shared_media_clock as clock


class SharedClockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ['source.mp4', 'voice.wav', 'composition.js', 'approval.md', 'browser.exe', 'cli.js']:
            (self.root/name).write_text(name, encoding='utf-8')
        html = '<div id="main" data-composition-id="main" data-start="0" data-duration="2" data-fps="2">'
        html += '<video id="base" src="source.mp4" data-start="0" data-duration="2" muted></video>'
        for i in range(2):
            html += f'<div id="host{i}" data-semantic-event-id="event{i}"><video id="v{i}" src="source.mp4" data-start="0" data-media-start="0" data-duration="2" muted></video></div>'
        html += '<audio id="voice" src="voice.wav" data-start="0" data-duration="2"></audio></div><script src="composition.js"></script>'
        (self.root/'index.html').write_text(html, encoding='utf-8')
        self.payload = {'direction':'authentic_product_editorial','events':[
            {'instance_id':f'event{i}','recipe_id':'A01','output_start':s,'output_end':e,
             'sound':{'decision':'intentionally_silent'}} for i,(s,e) in enumerate([(0.25,0.75),(1,1.5)])]}
        self.save('payload.json',self.payload)
        self.intent = {'schema_version':1,'kind':'shared_source_clock_intent',
            'authorization':'approved_qa_c_minimal_adaptation',
            'approval':self.ref('approval.md'),'payload':self.ref('payload.json'),
            'composition_id':'main','duration':2,'fps':2,'base_video_id':'base','audio_id':'voice',
            'video_source':self.ref('source.mp4'),'audio_source':self.ref('voice.wav'),
            'instances':[{'video_id':f'v{i}','host_id':f'host{i}','event_id':f'event{i}'} for i in range(2)],
            'project_files':[self.ref(n) for n in ['index.html','composition.js','source.mp4','voice.wav']]}
        self.save('intent.json',self.intent)
        self.bindings=clock.current_bindings(self.root,self.root/'intent.json')
        result={'ok':False,'strict':True,'browserSkipped':False}
        for section in ['lint','runtime','layout','motion','contrast']:
            result[section]={'ok':True,'errorCount':0,'warningCount':0,'findings':[]}
        result['lint']['warningCount']=1
        result['lint']['findings']=[{'code':'duplicate_media_discovery_risk','severity':'warning',
            'message':'Detected 3 matching video entries with the same source/start/duration.',
            'sourceFile':str(self.root/'index.html')}]
        self.save('stdout.json',result)
        self.raw={'exit_code':1,'command':['node',str(self.root/'cli.js'),'check',str(self.root),'--strict','--json'],
                  'tool':self.ref('cli.js'),'stdout':self.ref('stdout.json'),'inputs':self.bindings}
        self.save('strict.json',self.raw)
        times=clock.sample_times(self.intent,self.payload)
        rows=[]
        for direction,values in [('forward',times),('reverse',list(reversed(times)))]:
            for t in values:
                ids=['base']+[f'v{i}' for i,e in enumerate(self.payload['events']) if e['output_start']<=t<e['output_end']]
                rows.append({'direction':direction,'time':t,'active_video_ids':ids,
                    'media':copy.deepcopy(clock.inspect_project(self.root,self.intent,self.payload)['media'])})
        self.runtime={'schema_version':1,'producer':'shared-media-clock-runtime-v1',
            'collector':clock.file_ref(Path(clock.__file__)),'browser':self.ref('browser.exe'),
            'inputs':self.bindings,'rows':rows,'media':clock.inspect_project(self.root,self.intent,self.payload)['media']}
        self.save('runtime.json',self.runtime)

    def save(self,name,value):
        (self.root/name).write_text(json.dumps(value),encoding='utf-8')

    def ref(self,name):
        return clock.file_ref(self.root/name)

    def build(self):
        return clock.build_shared_clock_adaptation(project_root=self.root,intent_path=self.root/'intent.json',
            raw_strict_path=self.root/'strict.json',runtime_path=self.root/'runtime.json')

    def test_accepts_exact_intent_without_rewriting_raw(self):
        before=(self.root/'strict.json').read_bytes()
        result=self.build()
        self.assertEqual(result['effective_status'],'pass')
        self.assertEqual(result['raw_exit_code'],1)
        self.assertEqual(before,(self.root/'strict.json').read_bytes())
        self.save('adaptation.json',result)
        self.assertEqual(clock.validate_shared_clock_adaptation(self.root/'adaptation.json',project_root=self.root,
            intent_path=self.root/'intent.json',raw_strict_path=self.root/'strict.json',runtime_path=self.root/'runtime.json'),[])

    def test_other_warning_or_error_is_never_adapted(self):
        for field,value in [('warningCount',1),('errorCount',1)]:
            with self.subTest(field=field):
                data=json.loads((self.root/'stdout.json').read_text())
                data['runtime'][field]=value
                self.save('stdout.json',data)
                raw=copy.deepcopy(self.raw);raw['stdout']=self.ref('stdout.json');self.save('strict.json',raw)
                with self.assertRaises(ValueError): self.build()

    def test_drift_missing_or_wrong_bindings_rejected(self):
        (self.root/'composition.js').write_text('changed')
        with self.assertRaises(ValueError):self.build()

    def test_missing_runtime_samples_rejected(self):
        self.runtime['rows'].pop();self.save('runtime.json',self.runtime)
        with self.assertRaises(ValueError):self.build()

    def test_competing_a01_or_missing_base_rejected(self):
        self.runtime['rows'][0]['active_video_ids']=['v0','v1'];self.save('runtime.json',self.runtime)
        with self.assertRaises(ValueError):self.build()

    def test_non_strict_or_faked_success_rejected(self):
        self.raw['exit_code']=0;self.save('strict.json',self.raw)
        with self.assertRaises(ValueError):self.build()

    def test_runtime_media_drift_rejected(self):
        self.runtime['media'][1]['muted']=False;self.save('runtime.json',self.runtime)
        with self.assertRaises(ValueError):self.build()

    def test_transient_audio_or_source_drift_rejected(self):
        for key,value in [('muted',False),('src','other.mp4'),('mediaStart',0.1),
                          ('playbackRate',2),('volume',0.5),('loop',True),('currentSrcMatchesDeclared',False)]:
            with self.subTest(key=key):
                runtime=copy.deepcopy(self.runtime)
                runtime['rows'][2]['media'][1][key]=value
                self.save('runtime.json',runtime)
                with self.assertRaises(ValueError):self.build()

    def test_wrong_tool_or_project_command_rejected(self):
        for index in [1,3]:
            raw=copy.deepcopy(self.raw);raw['command'][index]=str(self.root/'unbound')
            self.save('strict.json',raw)
            with self.assertRaises(ValueError):self.build()

    def test_static_duplicate_id_audio_or_wrong_clock_rejected(self):
        original=(self.root/'index.html').read_text()
        for replacement in [original.replace('id="v0"','id="base"'),
                            original.replace('data-media-start="0"','data-media-start="0.1"'),
                            original.replace('</audio>','</audio><audio id="extra" src="voice.wav"></audio>')]:
            with self.subTest(replacement=replacement):
                (self.root/'index.html').write_text(replacement)
                with self.assertRaises(ValueError):clock.inspect_project(self.root,self.intent,self.payload)

    def test_unbound_css_or_module_dependencies_rejected(self):
        original=(self.root/'index.html').read_text()
        for suffix in ['<link rel="stylesheet" href="extra.css">','<script type="module">import "extra.js";</script>',
                       '<script>import("extra.js")</script>']:
            (self.root/'index.html').write_text(original+suffix)
            intent=copy.deepcopy(self.intent)
            intent['project_files'][0]=self.ref('index.html')
            with self.assertRaises(ValueError):clock.inspect_project(self.root,intent,self.payload)


if __name__=='__main__':unittest.main()
