from __future__ import annotations
import importlib.util,json,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/"scripts"/f"{name}.py");m=importlib.util.module_from_spec(spec);assert spec.loader;spec.loader.exec_module(m);return m
CACHE=load("render_with_cache"); OCCLUSION=load("detect_platform_occlusion")

class Phase3Tests(unittest.TestCase):
    def test_presets_are_dated_and_recommendations_explicit(self):
        data=json.loads((ROOT/"references"/"platform-presets.json").read_text(encoding="utf-8"))
        self.assertRegex(data["verified_on"],r"^\d{4}-\d{2}-\d{2}$")
        for preset in data["platforms"].values():
            self.assertTrue(preset["sources"]);self.assertTrue(preset["recommendation_fields"])

    def test_occlusion_catches_ui_and_opaque_layer(self):
        elements=[{"id":"caption","role":"caption","x0":.1,"y0":.8,"x1":.8,"y1":.95,"z":1},{"id":"panel","x0":.1,"y0":.8,"x1":.8,"y1":.95,"z":2,"opacity":1}]
        zones=[{"id":"description","x0":0,"y0":.78,"x1":.9,"y1":1}]
        codes={x["code"] for x in OCCLUSION.analyze(elements,zones)}
        self.assertIn("platform_ui_collision",codes);self.assertIn("opaque_layer_occlusion",codes)

    def test_resumes_and_invalidates_only_dependencies(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/"source.txt").write_text("A");(root/"caption.txt").write_text("one")
            copy_source="from pathlib import Path;Path('frames.txt').write_text(Path('source.txt').read_text())"
            graphics="from pathlib import Path;Path('graphics.txt').write_text(Path('frames.txt').read_text()+Path('caption.txt').read_text())"
            config={"name":"fixture","settings":{"version":1},"stages":[
                {"id":"extraction","inputs":["source.txt"],"outputs":["frames.txt"],"command":[sys.executable,"-c",copy_source]},
                {"id":"graphics_render","depends_on":["extraction"],"inputs":["caption.txt","frames.txt"],"outputs":["graphics.txt"],"command":[sys.executable,"-c",graphics]}]}
            cache=root/"cache";status=root/"status.json"
            first=CACHE.run_pipeline(config,root,cache,status,"extraction");self.assertEqual(first["state"],"interrupted_for_test")
            second=CACHE.run_pipeline(config,root,cache,status,None);self.assertEqual(second["stages"]["extraction"]["state"],"reused")
            self.assertEqual(second["state"],"completed")
            (root/"caption.txt").write_text("two")
            third=CACHE.run_pipeline(config,root,cache,status,None);self.assertEqual(third["stages"]["extraction"]["state"],"reused");self.assertEqual(third["stages"]["graphics_render"]["state"],"completed")
            (root/"frames.txt").write_text("corrupt")
            fourth=CACHE.run_pipeline(config,root,cache,status,None);self.assertEqual(fourth["stages"]["extraction"]["state"],"completed")
            (root/"source.txt").write_text("B")
            fifth=CACHE.run_pipeline(config,root,cache,status,None);self.assertEqual(fifth["stages"]["extraction"]["state"],"completed")

if __name__=="__main__":unittest.main()
