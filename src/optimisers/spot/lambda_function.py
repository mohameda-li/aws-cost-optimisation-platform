import csv
import json
import os
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError

try:
    from .cost_analysis import calculate_spot_cost
    from .recommendations import recommend_spot_optimisations
    from .savings import estimate_spot_savings
except ImportError:
    from cost_analysis import calculate_spot_cost
    from recommendations import recommend_spot_optimisations
    from savings import estimate_spot_savings


_BOTO_CFG = Config(retries={"max_attempts": 8, "mode": "standard"})


AWS_REGION = os.getenv("AWS_REGION", "eu-west-2")
HOURS_PER_MONTH = int(os.getenv("HOURS_PER_MONTH", "720"))
SUITABLE_ENV_KEYWORDS = [x.strip().lower() for x in os.getenv("SUITABLE_ENV_KEYWORDS", "dev,test,staging").split(",") if x.strip()]
SUITABLE_WORKLOAD_KEYWORDS = [x.strip().lower() for x in os.getenv("SUITABLE_WORKLOAD_KEYWORDS", "batch,analytics,processing").split(",") if x.strip()]


def _empty_response(reason: str | None = None):
    body = {
        "service": "spot",
        "resources_analysed": 0,
        "findings_count": 0,
        "baseline_monthly_cost": 0.0,
        "optimised_monthly_cost": 0.0,
        "total_monthly_savings": 0.0,
        "recommendations": [],
    }
    if reason:
        body["details"] = {"reason": reason}
    return {"statusCode": 200, "body": json.dumps(body)}


def _is_true_tag_value(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _infer_is_stateless(tags: dict) -> bool:
    workload = str(tags.get("WorkloadType", "")).lower()
    environment = str(tags.get("Environment", "")).lower()
    stateless_tag = str(tags.get("Stateless", "")).lower()

    return (
        _is_true_tag_value(stateless_tag)
        or any(k in workload for k in SUITABLE_WORKLOAD_KEYWORDS)
        or any(k in environment for k in SUITABLE_ENV_KEYWORDS)
    )


def _infer_is_batch(tags: dict) -> bool:
    workload = str(tags.get("WorkloadType", "")).lower()
    return "batch" in workload or "processing" in workload or _is_true_tag_value(tags.get("Batch", ""))


def _estimate_interruptions_30d(instance: dict) -> int:
    lifecycle = str(instance.get("InstanceLifecycle", "")).lower()
    if lifecycle == "spot":
        return 2
    return 0


def _write_live_usage_csv() -> str:
    ec2 = boto3.client("ec2", region_name=AWS_REGION, config=_BOTO_CFG)

    out_dir = Path("/tmp/spot")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "spot_usage_live.csv"

    try:
        resp = ec2.describe_instances(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        )
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"Failed to fetch EC2 instances: {type(e).__name__}")

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "workload_id",
            "instance_type",
            "hours_used",
            "interruptions_30d",
            "is_stateless",
            "is_batch",
        ])

        for reservation in resp.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                instance_id = instance.get("InstanceId")
                instance_type = instance.get("InstanceType")

                if not instance_id or not instance_type:
                    continue

                tags = {
                    t.get("Key"): t.get("Value")
                    for t in (instance.get("Tags") or [])
                    if t.get("Key")
                }

                writer.writerow([
                    instance_id,
                    instance_type,
                    HOURS_PER_MONTH,
                    _estimate_interruptions_30d(instance),
                    _infer_is_stateless(tags),
                    _infer_is_batch(tags),
                ])

    return str(out_csv)


def handler(event, context):
    try:
        usage_path = _write_live_usage_csv()
        pricing_path = os.getenv("SPOT_PRICING_PATH", "data/spot/spot_pricing.csv")

        cost_df = calculate_spot_cost(
            usage_path=usage_path,
            pricing_path=pricing_path,
        )

        if not cost_df:
            return _empty_response("No EC2 workloads found to analyse.")

        recommendations_df = recommend_spot_optimisations(cost_df)
        spot_savings = estimate_spot_savings(cost_df, recommendations_df)

        out = {
            "service": "spot",
            "resources_analysed": int(len(cost_df)),
            "findings_count": int(len(recommendations_df)),
            "baseline_monthly_cost": float(spot_savings.get("baseline_monthly_cost", 0.0)),
            "optimised_monthly_cost": float(spot_savings.get("optimised_monthly_cost", 0.0)),
            "total_monthly_savings": float(spot_savings.get("total_monthly_savings", 0.0)),
            "recommendations": recommendations_df,
            "per_resource_costs": spot_savings.get("per_resource_costs", {}),
            "details": {
                "region": AWS_REGION,
                "hours_per_month": HOURS_PER_MONTH,
            },
        }

        return {"statusCode": 200, "body": json.dumps(out)}

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "service": "spot",
                "error": "Spot optimiser failed",
                "details": str(e),
            }),
        }
