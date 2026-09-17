import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from diagnostic_stats import decompose_teacher_kl, paired_brier, analyze_kl_document


class DiagnosticTests(unittest.TestCase):
    def test_identity_random(self):
        rng = np.random.default_rng(42)
        for actions in (2, 5, 17):
            for repeats in (2, 4, 8):
                d = decompose_teacher_kl(rng.dirichlet(np.ones(actions), repeats),
                                        rng.dirichlet(np.ones(actions)))
                self.assertLess(abs(d["identity_residual"]), 1e-12)

    def test_teacher_mean_is_optimum_for_empirical_forward_kl(self):
        d = decompose_teacher_kl([[.8, .2], [.2, .8]], [.5, .5])
        self.assertAlmostEqual(d["empirical_mean_to_student_kl"], 0)
        self.assertGreater(d["empirical_teacher_spread_kl"], 0)

    def test_pairwise_is_not_spread(self):
        d = decompose_teacher_kl([[.8, .2], [.2, .8]], [.5, .5])
        self.assertGreater(d["pairwise_directed_teacher_kl_mean"],
                           d["empirical_teacher_spread_kl"])
        self.assertFalse(d["is_population_noise_floor"])

    def test_zero_teacher_support_allowed(self):
        d = decompose_teacher_kl([[1, 0], [0, 1]], [.5, .5])
        self.assertAlmostEqual(d["mean_teacher_to_student_kl"], np.log(2))
        self.assertIsNone(d["pairwise_directed_teacher_kl_mean"])
        self.assertEqual(d["pairwise_infinite_terms"], 2)

    def test_infinite_student_kl_rejected(self):
        with self.assertRaises(ValueError):
            decompose_teacher_kl([[.5, .5], [.8, .2]], [1, 0])

    def test_invalid_distribution_rejected(self):
        for p in ([.5, .4], [-.1, 1.1], [float("nan"), 1.]):
            with self.assertRaises(ValueError):
                decompose_teacher_kl([p, [.5, .5]], [.5, .5])

    def test_identical_predictions_paired_zero(self):
        rows = [{"cluster_id":str(i), "sample_id":"s", "y":i%2,
                 "p_model":.3, "p_baseline":.3} for i in range(30)]
        r = paired_brier(rows, repetitions=500)
        self.assertEqual(r["difference_percentile_interval_95"], [0., 0.])
        self.assertEqual(r["difference_model_minus_baseline"], 0)

    def test_cluster_weight_is_not_row_weight(self):
        rows = [{"cluster_id":"a", "sample_id":str(i), "y":0,
                 "p_model":0., "p_baseline":1.} for i in range(9)]
        rows.append({"cluster_id":"b", "sample_id":"0", "y":0,
                     "p_model":1., "p_baseline":0.})
        r = paired_brier(rows, repetitions=500)
        self.assertEqual(r["difference_model_minus_baseline"], 0)
        self.assertEqual(r["model_brier"], .5)

    def test_duplicate_pairs_rejected(self):
        row = {"cluster_id":"a", "sample_id":"0", "y":0,
               "p_model":0., "p_baseline":1.}
        with self.assertRaises(ValueError):
            paired_brier([row, row])

    def test_complex_design_rejected(self):
        row = {"cluster_id":"a", "sample_id":"0", "y":0,
               "p_model":0., "p_baseline":1., "training_seed":42}
        with self.assertRaises(ValueError):
            paired_brier([row])

    def test_forced_actions_excluded_from_macro(self):
        doc = {"score_space":"action_id", "states":[
            {"state_id":"s1", "episode_id":"e", "action_keys":["a", "b"],
             "teacher_policies":[[.8,.2], [.2,.8]], "student_policy":[.6,.4]},
            {"state_id":"s2", "episode_id":"e", "action_keys":["end"],
             "teacher_policies":[[1.], [1.]], "student_policy":[1.]},
        ]}
        r = analyze_kl_document(doc)
        self.assertEqual(r["decision_states"], 1)
        self.assertEqual(r["decision_episodes"], 1)
        self.assertAlmostEqual(r["episode_macro_decision_means"]["mean_teacher_to_student_kl"],
                               r["per_state"][0]["mean_teacher_to_student_kl"])

    def test_random_seed_reproducible(self):
        rows = [{"cluster_id":str(i), "sample_id":"s", "y":i%2,
                 "p_model":.1+i*.02, "p_baseline":.5} for i in range(20)]
        a = paired_brier(rows, repetitions=500, seed=10)
        b = paired_brier(rows, repetitions=500, seed=10)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
