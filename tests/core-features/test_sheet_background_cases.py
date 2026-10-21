"""Fixture and relationship controls for the real worksheet background runner."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
HAVE_PIL=importlib.util.find_spec("PIL") is not None

@unittest.skipUnless(HAVE_PIL,"worksheet image probes need Pillow")
class SheetBackgroundCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(ROOT/"scripts"))
        import test_sheet_background_runtime as runner
        cls.runner=runner
    def check_snapshot(self,parts):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"fixture.xlsx";self.runner.write(path,parts);return self.runner.snapshot(path)
    def test_each_sheet_resolves_its_own_same_relationship_id(self):
        r=self.runner;parts=r.package(ROOT/"tests/core-features/fixtures/sheet-core-features.xlsx")
        first=r.png((220,10,160,255));second=r.png((10,160,210,255))
        r.picture(parts,1,"../media/one.png",first);r.picture(parts,2,"../media/two.png",second)
        sheets=self.check_snapshot(parts)["sheets"]
        self.assertEqual(sheets[0]["image"],r.pixels(first));self.assertEqual(sheets[1]["image"],r.pixels(second))
        self.assertNotEqual(sheets[0]["image"],sheets[1]["image"])
    def test_removing_one_background_preserves_the_other(self):
        r=self.runner;parts=r.package(ROOT/"tests/core-features/fixtures/sheet-core-features.xlsx")
        r.picture(parts,1,None);sheets=self.check_snapshot(parts)["sheets"]
        self.assertFalse(sheets[0]["picture"]);self.assertTrue(sheets[1]["picture"])
        self.assertTrue(sheets[1]["mediaExists"])
    def test_alias_and_alpha_pixels_are_checked_independently_of_file_name(self):
        r=self.runner;parts=r.package(ROOT/"tests/core-features/fixtures/sheet-core-features.xlsx")
        data=r.png((220,10,160,128),(1,1));r.picture(parts,1,"../media/./alpha.png",data)
        item=self.check_snapshot(parts)["sheets"][0]
        self.assertEqual(item["target"],"xl/media/alpha.png");self.assertEqual(item["image"],r.pixels(data))
        self.assertIsNone(r.pixels(b"broken image"))
    def test_missing_media_is_not_mistaken_for_a_valid_background(self):
        r=self.runner;parts=r.package(ROOT/"tests/core-features/fixtures/sheet-core-features.xlsx")
        r.picture(parts,1,"../media/missing.png")
        item=self.check_snapshot(parts)["sheets"][0]
        self.assertTrue(item["picture"]);self.assertTrue(item["relationshipExists"])
        self.assertFalse(item["mediaExists"]);self.assertNotIn("image",item)

if __name__=="__main__":unittest.main()
