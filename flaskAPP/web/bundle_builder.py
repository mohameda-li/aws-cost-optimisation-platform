import json
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

from web_common import get_enabled_service_codes

logger = logging.getLogger(__name__)


def _hcl_string(value):
    return json.dumps("" if value is None else str(value))


def find_project_root(root_path: str) -> Path:
    search_roots = [Path(root_path).resolve(), Path(__file__).resolve().parent]
    seen = set()

    for origin in search_roots:
        for candidate in (origin, *origin.parents):
            candidate_str = str(candidate)
            if candidate_str in seen:
                continue
            seen.add(candidate_str)
            if (candidate / "src").exists() and (candidate / "flaskAPP").exists():
                return candidate

    current = Path(root_path).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "src").exists() and (candidate / "flaskAPP").exists():
            return candidate
    return current


def _copytree_clean(source_dir: Path, target_dir: Path):
    shutil.copytree(
        source_dir,
        target_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", "*.pyc"),
    )


def _zip_directory(source_dir: Path, zip_path: Path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path in sorted(source_dir.rglob("*")):
            if file_path.is_dir():
                continue
            zipf.write(file_path, file_path.relative_to(source_dir))


def generate_terraform_tfvars(customer_data, output_path):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    s3_target_buckets = customer_data.get("s3_target_buckets", [])
    target_buckets_csv = ",".join(s3_target_buckets)
    enabled_service_codes = get_enabled_service_codes(customer_data)
    enabled_services_hcl = json.dumps(enabled_service_codes)

    content = f'''aws_region                   = {_hcl_string(customer_data["aws_region"])}
customer_id                  = {_hcl_string(customer_data["customer_id"])}
company_name                 = {_hcl_string(customer_data["company_name"])}
report_bucket_name           = {_hcl_string(customer_data["report_bucket_name"])}
notification_email           = {_hcl_string(customer_data["notification_email"])}
schedule_expression          = {_hcl_string(customer_data["schedule_expression"])}
s3_default_days_since_access = {customer_data.get("s3_default_days_since_access", 60)}
s3_target_buckets            = {_hcl_string(target_buckets_csv)}
smtp_host                    = {_hcl_string(customer_data.get("smtp_host", ""))}
smtp_port                    = {int(customer_data.get("smtp_port", 587))}
smtp_username                = {_hcl_string(customer_data.get("smtp_username", ""))}
smtp_password                = {_hcl_string(customer_data.get("smtp_password", ""))}
smtp_sender                  = {_hcl_string(customer_data.get("smtp_sender", ""))}
smtp_use_tls                 = {json.dumps(bool(customer_data.get("smtp_use_tls", True)))}
run_initial_report_on_apply  = {json.dumps(bool(customer_data.get("run_initial_report_on_apply", True)))}
enabled_services             = {enabled_services_hcl}
'''

    output_file.write_text(content, encoding="utf-8")
    logger.info("TFVARS written to %s", output_file.resolve())


def generate_customer_config(customer_data, output_path):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    enabled_service_codes = get_enabled_service_codes(customer_data)
    config = {
        "customer": {
            "customer_id": customer_data["customer_id"],
            "company_name": customer_data["company_name"],
        },
        "deployment": {
            "aws_region": customer_data["aws_region"],
            "environment": "production",
            "deployment_mode": "customer-owned",
        },
        "enabled_services": enabled_service_codes,
        "services": {
            "s3": {
                "enabled": customer_data["services"].get("s3", False),
                "target_buckets": customer_data.get("s3_target_buckets", []),
                "default_days_since_access": customer_data.get("s3_default_days_since_access", 60),
            },
            "rds": {"enabled": customer_data["services"].get("rds", False)},
            "ecs": {"enabled": customer_data["services"].get("ecs", False)},
            "eks": {"enabled": customer_data["services"].get("eks", False)},
            "spot": {"enabled": customer_data["services"].get("spot", False)},
        },
        "reporting": {
            "report_formats": ["html", "json"],
            "email_recipient": customer_data["notification_email"],
            "report_s3_bucket": customer_data["report_bucket_name"],
            "email_delivery": {
                "method": "smtp",
                "smtp_host": customer_data.get("smtp_host", ""),
                "smtp_sender": customer_data.get("smtp_sender", ""),
            },
        },
        "schedule": {
            "enabled": True,
            "expression": customer_data["schedule_expression"],
            "run_initial_report_on_apply": bool(customer_data.get("run_initial_report_on_apply", True)),
        },
    }

    output_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    logger.info("Customer config written to %s", output_file.resolve())


def create_customer_bundle(app_root_path: str, customer_data):
    project_root = find_project_root(app_root_path)
    source_root = project_root / "src"
    runner_source_dir = source_root / "runner"
    optimisers_source_dir = source_root / "optimisers"
    data_source_dir = source_root / "data"
    service_package_filenames = {
        "s3": "s3_optimiser.zip",
        "rds": "rds_optimiser.zip",
        "ecs": "ecs_optimiser.zip",
        "eks": "eks_optimiser.zip",
        "spot": "spot_optimiser.zip",
    }

    template_dir = Path(app_root_path) / "package_templates" / "customer-deployment"
    bundles_root = Path(app_root_path) / "generated_bundles"
    bundle_folder_name = f'{customer_data["customer_id"]}-deployment'
    bundle_dir = bundles_root / bundle_folder_name
    zip_path = bundles_root / f"{bundle_folder_name}.zip"
    enabled_services = get_enabled_service_codes(customer_data)

    bundles_root.mkdir(parents=True, exist_ok=True)
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    if zip_path.exists():
        zip_path.unlink()

    shutil.copytree(template_dir, bundle_dir)

    bundle_data_dir = bundle_dir / "data"
    if bundle_data_dir.exists():
        shutil.rmtree(bundle_data_dir)

    lambda_dir = bundle_dir / "lambdas"
    if lambda_dir.exists():
        shutil.rmtree(lambda_dir)
    lambda_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="bundle-build-") as temp_dir:
        temp_root = Path(temp_dir)
        runner_stage = temp_root / "runner"
        runner_stage.mkdir(parents=True, exist_ok=True)
        _copytree_clean(runner_source_dir, runner_stage)

        for service in enabled_services:
            optimiser_source = optimisers_source_dir / service
            if optimiser_source.exists():
                _copytree_clean(optimiser_source, runner_stage / service)
            pricing_source = data_source_dir / service
            if pricing_source.exists():
                _copytree_clean(pricing_source, runner_stage / "data" / service)

        _zip_directory(runner_stage, lambda_dir / "runner.zip")

        for service in enabled_services:
            optimiser_source = optimisers_source_dir / service
            if not optimiser_source.exists():
                continue
            optimiser_stage = temp_root / f"{service}_optimiser"
            optimiser_stage.mkdir(parents=True, exist_ok=True)
            _copytree_clean(optimiser_source, optimiser_stage)
            pricing_source = data_source_dir / service
            if pricing_source.exists():
                _copytree_clean(pricing_source, optimiser_stage / "data" / service)
            _zip_directory(optimiser_stage, lambda_dir / service_package_filenames[service])

    tfvars_path = bundle_dir / "terraform" / "terraform.tfvars"
    config_path = bundle_dir / "config" / "customer_config.json"
    generate_terraform_tfvars(customer_data, tfvars_path)
    generate_customer_config(customer_data, config_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path in sorted(bundle_dir.rglob("*")):
            if file_path.is_dir():
                continue
            arcname = file_path.relative_to(bundles_root)
            zipf.write(file_path, arcname)

    logger.info("Bundle directory created at %s", bundle_dir)
    logger.info("Bundle zip created at %s", zip_path)
    return {
        "bundle_dir": str(bundle_dir),
        "zip_path": str(zip_path),
        "zip_filename": f"{bundle_folder_name}.zip",
    }
