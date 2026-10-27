import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from collect_sources import write_json
from run_collection import run


class RunnerTests(unittest.TestCase):
    def prepare(self, base):
        write_json(base/'machines.json',{'timezone':'Asia/Tokyo'})
        data={'machine_records':[{'date':'2026-10-26','model_id':'myj5','number':2221}],
              'forecast':{'snapshot_id':'unchanged'},'keep':'untouched',
              'machine_collection':{'status':'complete','models':{'myj5':{'rows':19}}}}
        write_json(base/'data.json',data)
        return data

    def test_timeout_keeps_data_but_not_stale_success(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);old=self.prepare(base)
            def timeout(*args,**kwargs): raise subprocess.TimeoutExpired('collector',240)
            result=run(base,timeout)
            data=json.loads((base/'data.json').read_text())
            self.assertEqual(data['machine_records'],old['machine_records'])
            self.assertEqual(data['forecast'],old['forecast'])
            self.assertEqual(data['keep'],'untouched')
            self.assertEqual(data['machine_collection']['status'],'error')
            self.assertEqual(data['machine_collection']['models'],{})
            self.assertEqual(data['machine_collection']['previous_attempt']['status'],'complete')
            self.assertTrue(result['process_failed'])
            self.assertEqual(len(list((base/'history'/'collection-runs').rglob('*.json'))),1)

    def test_nonzero_exit_is_recorded(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);self.prepare(base)
            def failure(*args,**kwargs): raise subprocess.CalledProcessError(2,'collector')
            self.assertTrue(run(base,failure)['process_failed'])

    def test_success_does_not_rewrite_data(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);self.prepare(base);original=(base/'data.json').read_bytes()
            def success(*args,**kwargs): self.assertEqual(kwargs['timeout'],240)
            result=run(base,success)
            self.assertFalse(result['process_failed'])
            self.assertEqual((base/'data.json').read_bytes(),original)

    def test_child_saved_data_is_preserved_even_when_it_fails(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);old=self.prepare(base)
            def failure(*args,**kwargs):
                write_json(base/'data.json',{**old,'child_saved':True})
                raise OSError('process failed')
            run(base,failure)
            self.assertTrue(json.loads((base/'data.json').read_text())['child_saved'])

    def test_invalid_data_is_not_overwritten(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);self.prepare(base);write_json(base/'data.json',[])
            with self.assertRaises(ValueError): run(base,lambda *a,**k:None)
            self.assertEqual(json.loads((base/'data.json').read_text()),[])


if __name__=='__main__': unittest.main()
