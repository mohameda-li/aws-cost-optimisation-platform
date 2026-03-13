import csv


def _read_csv_rows(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def calculate_s3_cost(usage_path: str, pricing_path: str) -> list[dict]:
    usage_rows = _read_csv_rows(usage_path)
    pricing_rows = _read_csv_rows(pricing_path)

    if not usage_rows:
        return []
    if not pricing_rows:
        raise ValueError("s3_pricing.csv is empty.")

    usage_required = {"bucket", "storage_class", "gb_used", "days_since_access"}
    pricing_required = {"storage_class", "price_per_gb"}

    missing_usage = usage_required - set(usage_rows[0].keys())
    missing_pricing = pricing_required - set(pricing_rows[0].keys())
    if missing_usage:
        raise ValueError(f"s3_usage.csv missing columns: {sorted(missing_usage)}")
    if missing_pricing:
        raise ValueError(f"s3_pricing.csv missing columns: {sorted(missing_pricing)}")

    pricing_map = {}
    pricing_model = pricing_rows[0].get("pricing_model", "per_gb_month")
    for row in pricing_rows:
        storage_class = str(row["storage_class"]).strip()
        try:
            pricing_map[storage_class] = float(row["price_per_gb"])
        except (TypeError, ValueError):
            raise ValueError(f"Invalid price_per_gb in S3 pricing data for storage class: {storage_class}")

    results = []
    for row in usage_rows:
        bucket = str(row.get("bucket", "")).strip()
        storage_class = str(row.get("storage_class", "")).strip()
        try:
            gb_used = float(row["gb_used"])
            days_since_access = float(row["days_since_access"])
        except (TypeError, ValueError):
            raise ValueError(f"Invalid numeric values in S3 usage data for bucket: {bucket}")

        if storage_class not in pricing_map:
            raise ValueError(f"Missing pricing for storage classes: ['{storage_class}']")

        price_per_gb = pricing_map[storage_class]
        results.append(
            {
                "bucket": bucket,
                "storage_class": storage_class,
                "gb_used": gb_used,
                "days_since_access": days_since_access,
                "price_per_gb": price_per_gb,
                "baseline_monthly_cost": gb_used * price_per_gb,
                "pricing_model": pricing_model,
                "pricing_source": pricing_path,
            }
        )

    return results
