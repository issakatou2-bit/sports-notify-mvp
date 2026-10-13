import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import update_protected_hashes as u


class HashTest(unittest.TestCase):
    def test_flat_nested_files_and_function(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fixtures=root/'scripts/fixtures/demo';fixtures.mkdir(parents=True)
            (root/'demo.py').write_bytes(b'def example():\r\n    return 1\r\n')
            file=fixtures/'protected-source.json'
            file.write_text(json.dumps({'demo.py':'0'*64,'files':{'demo.py':'0'*64},'functions':{'demo.py':{'example':'0'*64}}}))
            with patch.object(u,'ROOT',root):
                self.assertEqual(u.main([]),1)
                self.assertEqual(u.main(['--write']),0)
                self.assertEqual(u.main([]),0)
            data=json.loads(file.read_text())
            self.assertEqual(data['demo.py'],data['files']['demo.py'])
            self.assertEqual(data['functions']['demo.py']['example'],hashlib.sha256(b'def example():\n    return 1').hexdigest())


if __name__=='__main__':unittest.main(argv=[__file__])
