import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from botocore.config import Config

try:
    from .cost_analysis import calculate_rds_cost
    from .recommendations import recommend_rds_optimisations
    from .savings import estimate_rds_savings
except ImportError:
    from cost_analysis import calculate_rds_cost
    from recommendations import recommend_rds_optimisations
    from savings import estimate_rds_savings


_BOTO_CFG = Config(retries={"max_attempts": 8, "mode": "standard"})


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


def _get_env_str(primary: str, default: str = "", *aliases: str) -> str:
    for name in (primary, *aliases):
        value = os.getenv(name)
        if value is not None:
            return value
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


def _get_avg_metric(cloudwatch, db_instance_id: str, metric_name: str, start: datetime, end: datetime) -> float:
    response = cloudwatch.get_metric_statistics(
        Namespace="AWS/RDS",
        MetricName=metric_name,
        Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_instance_id}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Average"],
    )
    datapoints = response.get("Datapoints", [])
    values = [float(point["Average"]) for point in datapoints if "Average" in point]
    return round(sum(values) / len(values), 2) if values else 0.0


def _load_rds_usage_from_aws() -> list[dict]:
    region = _get_env_str("AWS_REGION", "eu-west-2")
    lookback_days = _get_env_int("LOOKBACK_DAYS", 30)

    rds = boto3.client("rds", region_name=region, config=_BOTO_CFG)
    cloudwatch = boto3.client("cloudwatch", region_name=region, config=_BOTO_CFG)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)

    rows = []
    marker = None

    while True:
        kwargs = {"MaxRecords": 100}
        if marker:
            kwargs["Marker"] = marker

        response = rds.describe_db_instances(**kwargs)
        dbs = response.get("DBInstances", [])

        for db in dbs:
            db_id = db.get("DBInstanceIdentifier")
            instance_class = db.get("DBInstanceClass")
            if not db_id or not instance_class:
                continue

            rows.append(
                {
                    "db_instance": db_id,
                    "instance_class": instance_class,
                    "hours_running": lookback_days * 24,
                    "avg_connections": _get_avg_metric(cloudwatch, db_id, "DatabaseConnections", start, end),
                    "avg_cpu_utilisation": _get_avg_metric(cloudwatch, db_id, "CPUUtilization", start, end),
                }
            )

        marker = response.get("Marker")
        if not marker:
            break

    return rows


def handler(event, context):
    try:
        region = _get_env_str("AWS_REGION", "eu-west-2")
        pricing_path = _resolve_pricing_path("RDS_PRICING_PATH", "data/rds/rds_pricing.csv", "rds_pricing.csv")

        usage_df = _load_rds_usage_from_aws()
        if not usage_df:
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "service": "rds",
                        "resources_analysed": 0,
                        "findings_count": 0,
                        "baseline_monthly_cost": 0.0,
                        "optimised_monthly_cost": 0.0,
                        "total_monthly_savings": 0.0,
                        "recommendations": [],
                        "per_resource_costs": {},
                        "details": {
                            "region": region,
                            "reason": "No RDS instances found to analyse.",
                        },
                    }
                ),
            }

        cost_df = calculate_rds_cost(usage_df, pricing_path)
        recommendations_df = recommend_rds_optimisations(cost_df)
        savings = estimate_rds_savings(recommendations_df)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "service": "rds",
                    "resources_analysed": int(len(cost_df)),
                    "findings_count": int(len(recommendations_df)),
                    "baseline_monthly_cost": float(savings.get("baseline_monthly_cost", 0.0)),
                    "optimised_monthly_cost": float(savings.get("optimised_monthly_cost", 0.0)),
                    "total_monthly_savings": float(savings.get("total_monthly_savings", 0.0)),
                    "recommendations": recommendations_df,
                    "per_resource_costs": savings.get("per_resource_costs", {}),
                    "details": {
                        "region": region,
                        "pricing_path": pricing_path,
                    },
                }
            ),
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "service": "rds",
                    "error": "RDS optimiser failed",
                    "details": str(e),
                }
            ),
        }
