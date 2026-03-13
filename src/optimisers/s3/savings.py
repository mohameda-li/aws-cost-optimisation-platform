import csv


def estimate_s3_savings(recommendations: list[dict], pricing_rows_or_path) -> dict:
    required = {
        "storage_class",
        "recommended_storage_class",
        "baseline_monthly_cost",
        "gb_used",
    }
    if recommendations:
        missing = required - set(recommendations[0].keys())
        if missing:
            raise ValueError(f"Missing required columns for S3 savings: {sorted(missing)}")

    if isinstance(pricing_rows_or_path, str):
        with open(pricing_rows_or_path, newline="", encoding="utf-8") as handle:
            pricing_rows = list(csv.DictReader(handle))
    else:
        pricing_rows = list(pricing_rows_or_path)

    if not pricing_rows:
        raise ValueError("s3_pricing.csv is empty")

    if "storage_class" not in pricing_rows[0] or "price_per_gb" not in pricing_rows[0]:
        raise ValueError("pricing data missing required columns: storage_class, price_per_gb")

    pricing_map = {}
    for row in pricing_rows:
        storage_class = str(row["storage_class"]).strip()
        try:
            pricing_map[storage_class] = float(row["price_per_gb"])
        except (TypeError, ValueError):
            raise ValueError(f"Invalid price_per_gb in pricing data for storage classes: [{storage_class}]")

    current_cost = sum(float(row["baseline_monthly_cost"]) for row in recommendations)
    projected_cost = 0.0

    for row in recommendations:
        recommended_class = row["recommended_storage_class"]
        new_price = pricing_map.get(recommended_class)
        if new_price is None:
            projected_cost += float(row["baseline_monthly_cost"])
            continue
        projected_cost += float(row["gb_used"]) * new_price

    estimated_savings = current_cost - projected_cost
    return {
        "current_cost": round(current_cost, 2),
        "projected_cost": round(projected_cost, 2),
        "estimated_savings": round(estimated_savings, 2),
    }
