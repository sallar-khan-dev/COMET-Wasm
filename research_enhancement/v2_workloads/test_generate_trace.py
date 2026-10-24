import copy
import json
import unittest
from pathlib import Path

from research_enhancement.v2_workloads.generate_trace import (
    canonical_bytes,
    generate,
)


class TestV2TraceGenerator(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = Path(
            "research_enhancement/v2_references/lr_iris_golden_v1.json"
        )
        cls.golden = json.loads(path.read_text())
        cls.reference = {
            r["row_index"]: r for r in cls.golden["records"]
        }

    def test_deterministic_bytes(self):
        a = generate(self.golden, 135, 42, 1)
        b = generate(self.golden, 135, 42, 1)
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))

    def test_tenant_independent_inputs(self):
        a = generate(self.golden, 135, 42, 1)
        b = generate(self.golden, 135, 42, 3)

        def inputs(trace):
            return [
                (r["source_row_index"], r["features"])
                for r in trace["requests"]
            ]

        self.assertEqual(inputs(a), inputs(b))

    def test_unique_request_ids(self):
        trace = generate(self.golden, 135, 42, 3)
        requests = trace["requests"]

        self.assertEqual(
            len({r["request_id"] for r in requests}), 135
        )
        self.assertEqual(
            [r["sequence"] for r in requests], list(range(135))
        )

    def test_complete_coverage(self):
        trace = generate(self.golden, 135, 42, 3)

        for start in range(0, 135, 45):
            block = trace["requests"][start:start + 45]
            self.assertEqual(
                {r["source_row_index"] for r in block},
                set(self.reference)
            )

    def test_invalid_inputs(self):
        for count, tenants in [(0, 1), (-1, 1), (10, 0)]:
            with self.subTest(count=count, tenants=tenants):
                with self.assertRaises(ValueError):
                    generate(self.golden, count, 42, tenants)

        bad = copy.deepcopy(self.golden)
        bad["records"][0]["features"][0] = float("nan")

        with self.assertRaises(ValueError):
            generate(bad, 10, 42, 1)

    def test_reference_preservation(self):
        trace = generate(self.golden, 135, 42, 3)

        for request in trace["requests"]:
            source = self.reference[request["source_row_index"]]

            self.assertEqual(request["features"], source["features"])
            self.assertEqual(
                request["expected_prediction"],
                source["expected_prediction"]
            )
            self.assertEqual(
                request["ground_truth_label"],
                source["ground_truth_label"]
            )

    def test_known_trace_digest(self):
        import hashlib

        trace = generate(self.golden, 135, 42, 1)
        digest = hashlib.sha256(canonical_bytes(trace)).hexdigest()

        self.assertEqual(
            digest,
            "087fdc612567380e5253c50a6cc23025d9e4acd73c8f0565d17fe78b1261325d"
        )


if __name__ == "__main__":
    unittest.main()
