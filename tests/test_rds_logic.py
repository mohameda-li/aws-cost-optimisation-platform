import tempfile
import unittest
from pathlib import Path

from src.optimisers.rds.cost_analysis import calculate_rds_cost
from src.optimisers.rds.recommendations import recommend_rds_optimisations
from src.optimisers.rds.savings import estimate_rds_savings


class TestRdsLogic(unittest.TestCase):
    def test_cost_recommendation_and_savings_flow(self):
        usage_rows = [
            {
                "db_instance": "db-idle",
                "instance_class": "db.t3.medium",
                "hours_running": 720,
                "avg_connections": 0,
                "avg_cpu_utilisation": 2,
            },
            {
                "db_instance": "db-small",
                "instance_class": "db.t3.medium",
                "hours_running": 720,
                "avg_connections": 2,
                "avg_cpu_utilisation": 10,
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            pricing_path = Path(tmp) / "rds_pricing.csv"
            pricing_path.write_text(
                "instance_class,cost_per_hour\n"
                "db.t3.medium,0.10\n",
                encoding="utf-8",
            )

            cost_rows = calculate_rds_cost(usage_rows, str(pricing_path))
            self.assertEqual(2, len(cost_rows))
            self.assertAlmostEqual(72.0, cost_rows[0]["baseline_monthly_cost"], places=2)

            recommendations = recommend_rds_optimisations(cost_rows)
            self.assertEqual("STOP", recommendations[0]["recommended_action"])
            self.assertEqual("DOWNSIZE", recommendations[1]["recommended_action"])

            savings = estimate_rds_savings(recommendations)
            self.assertAlmostEqual(144.0, savings["baseline_monthly_cost"], places=2)
            self.assertGreater(savings["total_monthly_savings"], 0.0)
            self.assertIn("db-idle", savings["per_resource_costs"])

    def test_missing_instance_pricing_raises(self):
        usage_rows = [
            {
                "db_instance": "db-1",
                "instance_class": "db.missing",
                "hours_running": 720,
                "avg_connections": 1,
                "avg_cpu_utilisation": 5,
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            pricing_path = Path(tmp) / "rds_pricing.csv"
            pricing_path.write_text(
                "instance_class,cost_per_hour\n"
                "db.t3.medium,0.10\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                calculate_rds_cost(usage_rows, str(pricing_path))


if __name__ == "__main__":
    unittest.main()
