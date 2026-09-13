import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "g1"
sys.path.insert(0, str(SCRIPT_DIR))

import discover_catalog  # noqa: E402


class DiscoveryHelpersTest(unittest.TestCase):
    def test_flatten_select2_groups_preserves_group(self):
        options = discover_catalog.flatten_options(
            [
                {
                    "text": "Individuales",
                    "children": [{"id": "2701", "text": "Activo"}],
                },
                {"id": "2310", "text": "Sucursales"},
            ]
        )
        self.assertEqual(
            options,
            [
                {"id": "2701", "text": "Activo", "group": "Individuales"},
                {"id": "2310", "text": "Sucursales", "group": None},
            ],
        )

    def test_canonical_json_is_order_independent_for_objects(self):
        first = discover_catalog.canonical_json_bytes({"b": 2, "a": 1})
        second = discover_catalog.canonical_json_bytes({"a": 1, "b": 2})
        self.assertEqual(first, second)

    def test_app_directory_removes_fragment(self):
        self.assertEqual(
            discover_catalog.app_directory("https://app.bde.es/sifdifu/es/#/"),
            "https://app.bde.es/sifdifu/es/",
        )

    def test_safe_url_keeps_entity_parentheses(self):
        self.assertEqual(
            discover_catalog.safe_url(
                "https://www.bde.es/app/sif/documentosAsociaciones/",
                "periodos",
                "202606",
                "2701",
                "0049(0002).json",
            ),
            "https://www.bde.es/app/sif/documentosAsociaciones/periodos/202606/2701/0049(0002).json",
        )


if __name__ == "__main__":
    unittest.main()
