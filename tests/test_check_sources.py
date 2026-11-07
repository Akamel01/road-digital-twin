"""Offline tests for scripts/check_sources.py. No network: fetch is replaced by a fake."""
import importlib.util
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("check_sources", os.path.join(ROOT, "scripts", "check_sources.py"))
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

GOOD_DOI = "10.1145/3592433"
GOOD_TITLE = "3D Gaussian Splatting for Real-Time Radiance Field Rendering"
WRONG_DOI = "10.1145/9999999.9999999"  # fixture: deliberately wrong DOI, Crossref has no such record

FIXTURE = [
    {"id": "good-paper", "type": "paper", "title": GOOD_TITLE, "authors": ["Kerbl, Bernhard"],
     "year": 2023, "venue": "ACM Transactions on Graphics", "doi": GOOD_DOI,
     "url": "https://doi.org/" + GOOD_DOI, "open_access": True, "questions": [1], "relevance": 3},
    {"id": "wrong-doi-paper", "type": "paper", "title": GOOD_TITLE, "authors": ["Kerbl, Bernhard"],
     "year": 2023, "venue": "ACM Transactions on Graphics", "doi": WRONG_DOI,
     "url": "https://doi.org/" + WRONG_DOI, "open_access": False, "questions": [1], "relevance": 2},
]


def fake_get(responses):
    """Build a fetch replacement that answers from a dict of url -> (status, ctype, body)."""
    def get(url):
        for key, value in responses.items():
            if url.startswith(key):
                return value
        return None, "", b""
    return get


def crossref_body(title):
    return json.dumps({"message": {"title": [title]}}).encode()


class CheckSourcesTest(unittest.TestCase):
    def test_correct_doi_passes(self):
        get = fake_get({"https://api.crossref.org/works/10.1145/3592433":
                        (200, "application/json", crossref_body(GOOD_TITLE))})
        self.assertEqual(cs.check_doi(FIXTURE[0], get), [])

    def test_wrong_doi_fails(self):
        get = fake_get({"https://api.crossref.org/works/": (404, "application/json", b"{}")})
        errs = cs.check_doi(FIXTURE[1], get)
        self.assertEqual(len(errs), 1)
        self.assertIn("Crossref HTTP 404", errs[0])

    def test_doi_with_mismatched_title_fails(self):
        get = fake_get({"https://api.crossref.org/works/": (200, "application/json",
                                                              crossref_body("Some other paper"))})
        errs = cs.check_doi(FIXTURE[1], get)
        self.assertEqual(len(errs), 1)
        self.assertIn("does not match", errs[0])

    def test_pdf_must_be_pdf(self):
        entry = {"pdf_url": "https://arxiv.org/pdf/2308.04079"}
        ok = fake_get({"https://arxiv.org/pdf/": (200, "application/pdf", b"%PDF-1.5")})
        html = fake_get({"https://arxiv.org/pdf/": (200, "text/html", b"<html>")})
        self.assertEqual(cs.check_pdf(entry, ok), [])
        self.assertEqual(len(cs.check_pdf(entry, html)), 1)

    def test_schema_flags_missing_fields(self):
        bad = {"id": "Bad_ID", "type": "paper", "title": "x", "url": "u", "questions": [9], "relevance": 1}
        errs = cs.check_schema(bad)
        self.assertTrue(any("kebab" in e for e in errs))
        self.assertTrue(any("questions" in e for e in errs))
        self.assertTrue(any("authors" in e for e in errs))

    def test_counts_and_question_minimums(self):
        errs, counts = cs.check_counts(FIXTURE)
        self.assertEqual(counts["paper"], 2)
        self.assertTrue(any("need at least 25 paper" in e for e in errs))
        self.assertTrue(any("question 1 has 2 sources" in e for e in errs))

    def test_citations_detect_unknown_and_uncited(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("Claim cites [good-paper] and [ghost-id].\n")
        try:
            errs = cs.check_citations(FIXTURE, f.name)
        finally:
            os.unlink(f.name)
        self.assertIn("related-work cites unknown id [ghost-id]", errs)
        self.assertIn("source wrong-doi-paper is never cited in related-work.md", errs)


if __name__ == "__main__":
    unittest.main()
