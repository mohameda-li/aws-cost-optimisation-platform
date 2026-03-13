import csv
from pathlib import Path


def calculate_rds_cost(usage_rows: list[dict], pricing_path: str) -> list[dict]:
    with open(pricing_path, newline="", encoding="utf-8") as handle:
        pricing_rows = list(csv.DictReader(handle))
    if not pricing_rows:
        raise ValueError("rds_pricing.csv is empty.")

    required_usage = {"db_instance", "instance_class", "hours_running", "avg_connections", "avg_cpu_utilisation"}
    required_pricing = {"instance_class", "cost_per_hour"}

    if usage_rows:
        missing_usage = required_usage - set(usage_rows[0].keys())
        if missing_usage:
            raise ValueError(f"RDS usage data missing columns: {sorted(missing_usage)}")
    missing_pricing = required_pricing - set(pricing_rows[0].keys())
    if missing_pricing:
        raise ValueError(f"RDS pricing data missing columns: {sorted(missing_pricing)}")

    pricing_map = {}
    for row in pricing_rows:
        instance_class = str(row["instance_class"]).strip()
        try:
            pricing_map[instance_class] = float(row["cost_per_hour"])
        except (TypeError, ValueError):
            raise ValueError("Invalid cost_per_hour values in RDS pricing data.")

    merged_rows = []
    for row in usage_rows:
        try:
            hours_running = float(row["hours_running"])
            avg_connections = float(row["avg_connections"])
            avg_cpu_utilisation = float(row["avg_cpu_utilisation"])
        except (TypeError, ValueError):
            raise ValueError("Invalid numeric values in RDS usage data.")

        instance_class = str(row["instance_class"]).strip()
        cost_per_hour = pricing_map.get(instance_class)
        if cost_per_hour is None:
            raise ValueError(f"Missing pricing for RDS instance classes: ['{instance_class}']")

        merged_rows.append(
            {
                "db_instance": row["db_instance"],
                "instance_class": instance_class,
                "hours_running": hours_running,
                "avg_connections": avg_connections,
                "avg_cpu_utilisation": avg_cpu_utilisation,
                "cost_per_hour": cost_per_hour,
                "baseline_monthly_cost": hours_running * cost_per_hour,
                "pricing_source": str(Path(pricing_path)),
            }
        )

    return merged_rows
