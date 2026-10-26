"""Packaged license texts retain complete documents and documented provenance."""

from hashlib import sha256
from pathlib import Path
import re
import unittest


LICENSES = Path(__file__).resolve().parents[1] / "py2fastrust" / "licenses"
EXPECTED_IDS = {
    "CC0-1.0", "Unlicense", "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause",
    "0BSD", "ISC", "Zlib", "BSL-1.0", "WTFPL", "MPL-2.0",
    "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
    "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later",
}


class LicenseCatalogTests(unittest.TestCase):
    def text(self, identifier):
        return (LICENSES / f"{identifier}.txt").read_text(encoding="utf-8")

    def test_every_catalog_license_can_be_selected_by_api(self):
        from py2fastrust import TranspileOptions, transpile
        from py2fastrust.settings import LICENSES as catalog
        self.assertEqual(set(catalog), EXPECTED_IDS)
        for identifier in sorted(EXPECTED_IDS):
            with self.subTest(identifier=identifier):
                result = transpile('print(1)\n', TranspileOptions(license=identifier.lower()))
                self.assertTrue(result.success, result.diagnostics)
                self.assertTrue(result.rust_source.startswith(f'// LICENSE: {identifier}\n'))
                self.assertGreater(len(result.rust_source), len(self.text(identifier)))

    def test_exact_spdx_catalog_has_no_empty_or_html_resources(self):
        actual = {path.stem for path in LICENSES.glob("*.txt")} - {"NOTICE"}
        self.assertEqual(actual, EXPECTED_IDS)
        for identifier in sorted(EXPECTED_IDS):
            with self.subTest(identifier=identifier):
                text = self.text(identifier)
                self.assertGreater(len(text), 200)
                self.assertTrue(text.endswith("\n"))
                self.assertNotIn("<!DOCTYPE", text)
                self.assertNotIn("<html", text)

    def test_manifest_covers_each_resource_and_its_distributed_bytes(self):
        notice = (LICENSES / "NOTICE.txt").read_text(encoding="utf-8")
        entries = re.findall(
            r"^ID: (\S+)\nFile: (\S+)\nSPDX: (\S+)\nPublisher: ([^\n]+)\nSHA256: ([0-9a-f]{64})$",
            notice, re.MULTILINE,
        )
        self.assertEqual(len(entries), len(EXPECTED_IDS))
        self.assertEqual({entry[0] for entry in entries}, EXPECTED_IDS)
        for identifier, filename, spdx, publisher, digest in entries:
            with self.subTest(identifier=identifier):
                self.assertEqual(filename, f"{identifier}.txt")
                self.assertEqual(spdx, f"https://spdx.org/licenses/{identifier}.html")
                self.assertTrue(publisher.startswith("https://"))
                self.assertEqual(sha256((LICENSES / filename).read_bytes()).hexdigest(), digest)

    def test_large_license_sections_and_application_appendices_are_complete(self):
        required = {
            "Apache-2.0": ("9. Accepting Warranty or Additional Liability.",
                           "APPENDIX: How to apply the Apache License to your work.",
                           "limitations under the License."),
            "MPL-2.0": ("10. Versions of the License", "Exhibit A - Source Code Form License Notice",
                        "Exhibit B -", "Incompatible With Secondary Licenses"),
            "GPL-2.0-only": ("Version 2, June 1991", "12.", "How to Apply These Terms to Your New Programs",
                             "consider it more useful to permit linking proprietary"),
            "GPL-3.0-only": ("Version 3, 29 June 2007", "17. Interpretation of Sections 15 and 16.",
                             "How to Apply These Terms to Your New Programs",
                             "<https://www.gnu.org/licenses/why-not-lgpl.html>"),
            "LGPL-2.1-only": ("Version 2.1, February 1999", "16.",
                              "How to Apply These Terms to Your New Libraries",
                              "signature of Moe Ghoul"),
        }
        for identifier, phrases in required.items():
            text = self.text(identifier)
            for phrase in phrases:
                with self.subTest(identifier=identifier, phrase=phrase):
                    self.assertTrue(phrase in text, f"{identifier} is missing {phrase!r}")

    def test_gnu_only_and_or_later_preserve_the_same_official_versioned_text(self):
        for family in ("GPL-2.0", "GPL-3.0", "LGPL-2.1", "LGPL-3.0"):
            with self.subTest(family=family):
                self.assertEqual(self.text(f"{family}-only"), self.text(f"{family}-or-later"))
        notice = (LICENSES / "NOTICE.txt").read_text(encoding="utf-8")
        self.assertIn("the chosen SPDX identifier", notice)

    def test_lgpl3_contains_its_supplement_and_the_full_referenced_gpl3(self):
        gpl = self.text("GPL-3.0-only")
        for suffix in ("only", "or-later"):
            text = self.text(f"LGPL-3.0-{suffix}")
            self.assertIn("GNU LESSER GENERAL PUBLIC LICENSE", text)
            self.assertIn("6. Revised Versions of the GNU Lesser General Public License.", text)
            self.assertTrue(text.endswith(gpl))
            self.assertIn("permanent authorization for you to choose that version", text)

    def test_copyright_templates_attribute_source_authors_and_keep_license_authors(self):
        for identifier in ("MIT", "0BSD", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib"):
            text = self.text(identifier)
            with self.subTest(identifier=identifier):
                self.assertIn("the authors of the original Python source", text)
                self.assertNotIn("Regents of the University of California", text)
                self.assertNotIn("<year>", text)
                self.assertNotIn("<owner>", text)
        self.assertIn("Copyright (C) 2004 Sam Hocevar <sam@hocevar.net>", self.text("WTFPL"))
        self.assertIn("Everyone is permitted to copy and distribute verbatim", self.text("WTFPL"))


if __name__ == "__main__":
    unittest.main()
