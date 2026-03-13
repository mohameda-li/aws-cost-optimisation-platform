import csv
import tempfile
import unittest
from pathlib import Path

from src.optimisers.s3.cost_analysis import calculate_s3_cost
from src.optimisers.s3.recommendations import recommend_s3_optimisations
from src.optimisers.s3.savings import estimate_s3_savings


class TestS3Logic(unittest.TestCase):
    def test_cost_recommendations_and_savings(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            usage_path = tmp_path / "s3_usage.csv"
            pricing_path = tmp_path / "s3_pricing.csv"

            usage_path.write_text(
                "bucket,storage_class,gb_used,days_since_access\n"
                "archive-bucket,STANDARD,100,120\n"
                "warm-bucket,STANDARD,50,45\n",
                encoding="utf-8",
            )
            pricing_path.write_text(
                "storage_class,price_per_gb\n"
                "STANDARD,0.023\n"
                "STANDARD_IA,0.0125\n"
                "GLACIER,0.004\n",
                encoding="utf-8",
            )

            cost_rows = calculate_s3_cost(str(usage_path), str(pricing_path))
            self.assertEqual(2, len(cost_rows))
            self.assertAlmostEqual(2.30, cost_rows[0]["baseline_monthly_cost"], places=2)

            recommendations = recommend_s3_optimisations(cost_rows)
            self.assertEqual("GLACIER", recommendations[0]["recommended_storage_class"])
            self.assertEqual("STANDARD_IA", recommendations[1]["recommended_storage_class"])

            savings = estimate_s3_savings(recommendations, str(pricing_path))
            self.assertEqual({"current_cost", "projected_cost", "estimated_savings"}, set(savings.keys()))
            self.assertGreater(savings["estimated_savings"], 0.0)

    def test_missing_pricing_column_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            usage_path = tmp_path / "s3_usage.csv"
            pricing_path = tmp_path / "s3_pricing.csv"

            usage_path.write_text(
                "bucket,storage_class,gb_used,days_since_access\n"
                "archive-bucket,STANDARD,100,120\n",
                encoding="utf-8",
            )
            pricing_path.write_text(
                "storage_class,wrong_column\n"
                "STANDARD,0.023\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                calculate_s3_cost(str(usage_path), str(pricing_path))


if __name__ == "__main__":
    unittest.main()
