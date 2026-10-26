"""Бинарные данные сертификата должны сравниваться по содержимому."""
import hashlib
import json
import runpy
from pathlib import Path
from unittest import TestCase


class AcceptanceRetentionTests(TestCase):
    scripts = ("prepare_program_solutions_browser.py", "verify_program_solutions_dev.py")

    def functions(self):
        root = Path(__file__).resolve().parents[1]
        for name in self.scripts:
            yield name, runpy.run_path(str(root / "scripts" / name))["stable_json_value"]

    def test_independent_binary_values_with_equal_content_have_equal_hashes(self):
        payload = bytes(range(256))
        for name, encode in self.functions():
            with self.subTest(script=name):
                variants = [memoryview(payload), memoryview(bytes(payload)), payload, bytearray(payload)]
                hashes = {
                    hashlib.sha256(json.dumps({"content": value}, default=encode).encode()).hexdigest()
                    for value in variants
                }
                self.assertEqual(len(hashes), 1)

    def test_changed_content_and_false_zero_are_distinguished(self):
        for name, encode in self.functions():
            with self.subTest(script=name):
                values = [memoryview(b"before"), memoryview(b"after"), 0, False, None]
                hashes = {
                    hashlib.sha256(json.dumps({"value": value}, default=encode).encode()).hexdigest()
                    for value in values
                }
                self.assertEqual(len(hashes), len(values))
