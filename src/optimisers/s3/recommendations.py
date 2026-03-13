def recommend_s3_optimisations(cost_rows: list[dict]) -> list[dict]:
    if not cost_rows:
        return []

    required = {
        "bucket",
        "storage_class",
        "gb_used",
        "days_since_access",
        "baseline_monthly_cost",
    }
    missing = required - set(cost_rows[0].keys())
    if missing:
        raise ValueError(f"Missing required columns for S3 recommendations: {sorted(missing)}")

    recommendations = []
    for row in cost_rows:
        days_since_access = float(row.get("days_since_access", 0.0) or 0.0)
        recommended_storage_class = row["storage_class"]
        recommendation_reason = "No change recommended"

        if 30 < days_since_access <= 90 and row["storage_class"] == "STANDARD":
            recommended_storage_class = "STANDARD_IA"
            recommendation_reason = "Object appears infrequently accessed and may be suitable for STANDARD_IA"
        elif days_since_access > 90:
            recommended_storage_class = "GLACIER"
            recommendation_reason = "Object appears cold and may be suitable for GLACIER archival storage"

        recommendations.append(
            {
                "bucket": row["bucket"],
                "storage_class": row["storage_class"],
                "recommended_storage_class": recommended_storage_class,
                "gb_used": float(row["gb_used"]),
                "baseline_monthly_cost": float(row["baseline_monthly_cost"]),
                "days_since_access": days_since_access,
                "recommendation_reason": recommendation_reason,
            }
        )

    return recommendations
