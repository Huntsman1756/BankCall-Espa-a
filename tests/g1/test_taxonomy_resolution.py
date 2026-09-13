"""G1-C.1 tests: schemaRef extraction and generation resolution."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "g1"))
from taxonomy_dts import extract_schemaref, generation_from_entrypoint


INSTANCE = (
    b'<?xml version="1.0"?>\n'
    b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
    b'xmlns:link="http://www.xbrl.org/2003/linkbase" '
    b'xmlns:xlink="http://www.w3.org/1999/xlink">'
    b'<link:schemaRef xlink:type="simple" '
    b'xlink:href="http://www.bde.es/es/fr/xbrl/fws/publicos/circ-4-2017/2018-01-01/mod/ps_in1.xsd"/>'
    b'</xbrli:xbrl>'
)


class TestSchemaRef(unittest.TestCase):
    def test_extract(self):
        self.assertEqual(
            extract_schemaref(INSTANCE),
            "http://www.bde.es/es/fr/xbrl/fws/publicos/circ-4-2017/2018-01-01/mod/ps_in1.xsd")

    def test_missing(self):
        self.assertIsNone(extract_schemaref(b"<xbrl/>"))

    def test_generations(self):
        self.assertEqual(
            generation_from_entrypoint(
                "http://www.bde.es/es/fr/xbrl/fws/publicos/circ-4-2017/2018-01-01/mod/ps_in1.xsd"),
            "publicos_2018_01")
        self.assertEqual(
            generation_from_entrypoint(
                "https://www.bde.es/es/fr/xbrl/fws/publicos/circ-4-2017/2018-12-01/mod/pi_in1.xsd"),
            "publicos_2018_12")
        self.assertEqual(
            generation_from_entrypoint(
                "http://www.bde.es/es/fr/xbrl/fws/publicos/circ-4-2017/2023-03-01/mod/pc_con1.xsd"),
            "publicos_2023_03")

    def test_unknown_path_not_invented(self):
        self.assertIsNone(generation_from_entrypoint(
            "http://www.bde.es/es/fr/xbrl/fws/other/2020-01-01/mod/x.xsd"))
        self.assertIsNone(generation_from_entrypoint(
            "http://www.bde.es/es/fr/xbrl/fws/publicos/circ-4-2017/2099-01-01/mod/x.xsd"))


if __name__ == "__main__":
    unittest.main()
