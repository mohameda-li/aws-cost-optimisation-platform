import csv
import json
import os
from pathlib import Path
from datetime import datetime, timezone

import boto3

try:
    from .cost_analysis import calculate_s3_cost
    from .recommendations import recommend_s3_optimisations
    from .savings import estimate_s3_savings
except ImportError:
    from cost_analysis import calculate_s3_cost
    from recommendations import recommend_s3_optimisations
    from savings import estimate_s3_savings


SERVICE = "s3"


def _get_env_str(primary: str, default: str = "", *aliases: str) -> str:
    for name in (primary, *aliases):
        value = os.getenv(name)
        if value is not None:
            return value
    return default


def _get_env_int(primary: str, default: int, *aliases: str) -> int:
    for name in (primary, *aliases):
        value = os.getenv(name)
        if value is None:
            continue
        try:
            return int(value)
        except ValueError:
            continue
    return default


def _resolve_pricing_path(env_name: str, *candidates: str) -> str:
    explicit = os.getenv(env_name)
    if explicit and Path(explicit).exists():
        return explicit

    module_path = Path(__file__).resolve()
    search_roots = [module_path.parent, module_path.parent.parent, Path("/var/task")]

    for root in search_roots:
        for candidate in candidates:
            path = root / candidate
            if path.exists():
                return str(path)

    return candidates[0]


def parse_target_buckets() -> list[str]:
    raw = _get_env_str("TARGET_BUCKETS", "", "S3_TARGET_BUCKETS").strip()
    if not raw:
        return []
    return [bucket.strip() for bucket in raw.split(",") if bucket.strip()]


def lambda_handler(event, context):
    event = event or {}
    region = _get_env_str("AWS_REGION", "eu-west-2")
    customer_id = _get_env_str("CUSTOMER_ID", event.get("customer", "unknown"))
    organisation_name = _get_env_str("ORGANISATION_NAME", _get_env_str("COMPANY_NAME", event.get("customer", "unknown")))
    report_bucket = _get_env_str("REPORT_BUCKET", "", "REPORT_BUCKET_NAME")
    report_email = _get_env_str("REPORT_EMAIL", "", "NOTIFICATION_EMAIL")
    default_days_since_access = _get_env_int("DEFAULT_DAYS_SINCE_ACCESS", 60, "S3_DEFAULT_DAYS_SINCE_ACCESS")
    pricing_path = _resolve_pricing_path("S3_PRICING_PATH", "data/s3/s3_pricing.csv", "s3_pricing.csv")
    target_buckets = parse_target_buckets()

    s3 = boto3.client("s3", region_name=region)

    output_dir = Path("/tmp")
    usage_csv = output_dir / "s3_usage_runtime.csv"

    rows_written = 0
    objects_scanned = 0
    buckets_scanned = 0
    skipped_buckets = []

    with usage_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["bucket", "gb_used", "storage_class", "days_since_access"])

        buckets_response = s3.list_buckets()
        bucket_names = [bucket["Name"] for bucket in buckets_response.get("Buckets", [])]
        excluded_buckets = {report_bucket} if report_bucket else set()

        if target_buckets:
            bucket_names = [name for name in bucket_names if name in target_buckets]

        bucket_names = [name for name in bucket_names if name not in excluded_buckets]

        for bucket_name in bucket_names:
            buckets_scanned += 1
            totals = {}
            token = None

            while True:
                kwargs = {"Bucket": bucket_name, "MaxKeys": 1000}
                if token:
                    kwargs["ContinuationToken"] = token

                try:
                    page = s3.list_objects_v2(**kwargs)
                except Exception as exc:
                    skipped_buckets.append(
                        {
                            "bucket": bucket_name,
                            "reason": str(exc)
                        }
                    )
                    break

                for obj in page.get("Contents", []):
                    objects_scanned += 1
                    size = obj.get("Size", 0)
                    storage_class = (obj.get("StorageClass") or "STANDARD").upper()
                    totals[storage_class] = totals.get(storage_class, 0) + size

                if page.get("IsTruncated"):
                    token = page.get("NextContinuationToken")
                else:
                    break

            for storage_class, bytes_used in totals.items():
                gb_used = round(bytes_used / (1024 ** 3), 4)
                writer.writerow([bucket_name, gb_used, storage_class, default_days_since_access])
                rows_written += 1

    cost_df = calculate_s3_cost(
        usage_path=str(usage_csv),
        pricing_path=pricing_path,
    )

    if not cost_df:
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "service": SERVICE,
                    "customer_id": customer_id,
                    "organisation_name": organisation_name,
                    "recommendations": [],
                    "savings": {
                        "baseline_monthly_cost": 0.0,
                        "optimised_monthly_cost": 0.0,
                        "total_monthly_savings": 0.0,
                    },
                    "details": {
                        "region": region,
                        "report_bucket": report_bucket,
                        "report_email": report_email,
                        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                        "reason": "No S3 rows available to analyse."
                    }
                }
            ),
        }

    recommendations_df = recommend_s3_optimisations(cost_df)
    savings = estimate_s3_savings(recommendations_df, pricing_path)

    response = {
        "service": SERVICE,
        "customer_id": customer_id,
        "organisation_name": organisation_name,
        "recommendations": recommendations_df,
        "savings": {
            "baseline_monthly_cost": float(savings["current_cost"]),
            "optimised_monthly_cost": float(savings["projected_cost"]),
            "total_monthly_savings": float(savings["estimated_savings"]),
        },
            "details": {
                "region": region,
                "report_bucket": report_bucket,
                "report_email": report_email,
                "target_buckets": target_buckets,
                "excluded_buckets": sorted(excluded_buckets),
                "buckets_scanned": buckets_scanned,
                "objects_scanned": objects_scanned,
                "rows_written": rows_written,
                "skipped_buckets": skipped_buckets,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    }

    return {
        "statusCode": 200,
        "body": json.dumps(response),
    }


# Runner expects "handler"; S3 uses "lambda_handler" for AWS Lambda entrypoint.
handler = lambda_handler
