"""
Test Suite for Ranuk BioSpan 5.0 Core Algorithms & RC4 Crypto.
"""
import unittest
import base64
from ranuk_biospan.collectors.biospan_health import (
    compute_recovery_score,
    compute_day_strain,
    optimal_strain_target,
    compute_healthspan,
)
from ranuk_biospan.collectors.xiaomi_cloud import (
    _rc4_crypt,
    _gen_nonce,
    _gen_signed_nonce,
)


class TestBioSpanAlgorithms(unittest.TestCase):
    def test_recovery_score_range_and_sensitivity(self):
        # Optimal recovery with high HRV and low RHR
        rec_high = compute_recovery_score(
            hrv_ms=95, rhr=50, sleep_perf=95, spo2=98.5, base_hrv=70.0, base_rhr=56.0
        )
        self.assertGreaterEqual(rec_high, 80)
        self.assertLessEqual(rec_high, 100)

        # Compromised recovery with depressed HRV and elevated RHR
        rec_low = compute_recovery_score(
            hrv_ms=35, rhr=75, sleep_perf=60, spo2=95.0, base_hrv=70.0, base_rhr=56.0
        )
        self.assertLessEqual(rec_low, 35)
        self.assertGreaterEqual(rec_low, 1)

    def test_day_strain_calculation(self):
        # Sedentary day: minimal strain
        strain_low = compute_day_strain({"z1": 10, "z2": 5, "z3": 0, "z4": 0, "z5": 0}, strength_min=0, steps=2000)
        self.assertLess(strain_low, 6.0)

        # High intensity interval day: elevated strain
        strain_high = compute_day_strain({"z1": 30, "z2": 45, "z3": 35, "z4": 25, "z5": 12}, strength_min=60, steps=14000)
        self.assertGreater(strain_high, 14.0)
        self.assertLessEqual(strain_high, 21.0)

    def test_optimal_strain_recommendation(self):
        target_green = optimal_strain_target(90)
        self.assertGreaterEqual(target_green["min"], 13.0)

        target_red = optimal_strain_target(20)
        self.assertLessEqual(target_red["max"], 10.0)

    def test_phenoage_healthspan_model(self):
        profile = {
            "chronological_age": 30.0,
            "weight_kg": 85.0,
            "height_cm": 180.0,
            "max_hr": 190,
            "baseline_rhr": 55.0,
            "baseline_hrv": 75.0,
        }
        days = [
            {
                "rhr": 52,
                "hrv_ms": 85,
                "vo2_max": 52.0,
                "sleep_hours": 8.0,
                "deep_sleep_min": 110,
                "rem_sleep_min": 120,
                "sleep_consistency": 88.0,
                "recovery_score": 85,
                "steps": 10500,
                "strength_min": 50,
                "hr_zones_json": '{"z1":30,"z2":40,"z3":20,"z4":10,"z5":5}',
            }
        ]
        result = compute_healthspan(profile, days)
        # Outstanding cardiovascular profile should reduce biological age (negative delta)
        self.assertLess(result["whoop_age"], result["chronological_age"])
        self.assertLess(result["pace_of_aging"], 1.0)

    def test_rc4_crypt_symmetry(self):
        key = b"16_byte_secret_k"
        plaintext = b'{"status":"ok","heart_rate":64,"watermark":1570000000000}'
        ciphertext = _rc4_crypt(key, plaintext)
        decrypted = _rc4_crypt(key, ciphertext)
        self.assertEqual(plaintext, decrypted)

    def test_nonce_and_signed_nonce(self):
        nonce = _gen_nonce()
        self.assertEqual(len(nonce), 12)
        ssecurity = b"xiaomi_test_ssecurity_sample_32"
        snonce = _gen_signed_nonce(ssecurity, nonce)
        self.assertEqual(len(snonce), 32)


if __name__ == "__main__":
    unittest.main()
