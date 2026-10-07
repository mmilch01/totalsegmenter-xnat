import os
import sys
import json
import datetime
import argparse
import subprocess
import yaml
from pathlib import Path
pymipl_path = Path("/opt/packages/pymipl")
sys.path.append(str(pymipl_path))
sys.path.append(str(pymipl_path / "xnat_workflow"))

from dicom_sort import analyze_dir, reindex_to_structurals_and_segs
import workflow_adapters as wa


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run Total Segmenter liver tumor segmentation for CT structural scans in an XNAT session."
    )
    parser.add_argument("--project", required=True, help="XNAT project label.")
    parser.add_argument("--session", help="XNAT experiment/session label or ID.")
    parser.add_argument("--host", help="XNAT host URL. Defaults to XNAT_HOST.")
    parser.add_argument("--user", help="XNAT username. Defaults to XNAT_USER.")
    parser.add_argument("--pass", dest="password", help="XNAT password. Defaults to XNAT_PASS.")
    args = parser.parse_args()

    env_fallbacks = {
        "host": "XNAT_HOST",
        "user": "XNAT_USER",
        "password": "XNAT_PASS",
    }
    missing = []
    for attr, env_name in env_fallbacks.items():
        value = getattr(args, attr)
        if value in (None, "", f"${env_name}", f"${{{env_name}}}"):
            value = os.environ.get(env_name)
            setattr(args, attr, value)
        if not getattr(args, attr):
            missing.append(f"--{attr if attr != 'password' else 'pass'} or {env_name}")
    if missing:
        parser.error("missing required XNAT connection settings: " + ", ".join(missing))
    return args


def normalize_xnat_input(input_root, view_root, experiment):
    """Return a project-shaped input path for dicom_sort."""
    project_level_experiments = input_root / "experiments"
    experiment_level_scans = input_root / "SCANS"
    if project_level_experiments.is_dir():
        return input_root / "experiments"
    if experiment_level_scans.is_dir():
        if not experiment:
            raise ValueError("Experiment-level /input detected, but --session was not provided.")
        experiment_dir = view_root / "experiments" / experiment
        experiment_dir.mkdir(parents=True, exist_ok=True)
        scans_link = experiment_dir / "SCANS"
        if scans_link.exists():
            if scans_link.resolve() != experiment_level_scans.resolve():
                raise ValueError(f"{scans_link} already exists and does not point to {experiment_level_scans}.")
        else:
            scans_link.symlink_to(experiment_level_scans, target_is_directory=True)
        return view_root / "experiments"
    raise ValueError("Unrecognized /input layout. Expected /input/experiments/... or /input/SCANS/...")


def main():
    args = parse_args()
    safe_args = argparse.Namespace(**vars(args))
    safe_args.password = "***"
    print(f"input arguments: {safe_args}")

    rebuild_directory_structure = True
    project = args.project
    root_dir = Path("/workdir/processing")
    root_dir.mkdir(parents=True, exist_ok=True)

    local_workdir_path = root_dir / project
    xnat_project_path = normalize_xnat_input(Path("/input"), Path("/workdir/input"), args.session)
    directory_structure_file = local_workdir_path / "project_dir_structure.json"
    xnat_structure_file = local_workdir_path / "xnat_structure.json"
    scanlist_file = local_workdir_path / "scans.csv"

    if rebuild_directory_structure:
        os.makedirs(os.path.dirname(directory_structure_file), exist_ok=True)
        d = analyze_dir(xnat_project_path, directory_structure_file)
    else:
        with open(directory_structure_file, "r") as file:
            d = json.load(file)

    subjects, scans = reindex_to_structurals_and_segs(d, xnat_structure_file, scanlist_file)

    #Filter out scans with no existing segmentations
    scans = [
        scan for scan in scans
        if any(
            key.startswith("SegScan") and value not in (None, "", "NA")
            for key, value in scan.items()
        )
    ]
    print(f"Number of structural scans with existing segmentations: {len(scans)}")

    if len(scans) == 0:
        raise ValueError("No structural scans with existing Seg/RTStruct segmentations found in the project.")

    workflow_id = "ABDOMINAL_CT_SEGMENTATION"
    user_env_repo = "/opt/packages/user/env_repo"
    user_src_repo = "/opt/packages/user/alg_repo"

    global_vars = wa.init_global_vars(
        "jupyter",
        project,
        workflow_id,
        g_user_env_repo=user_env_repo,
        g_user_src_repo=user_src_repo,
        g_input_mount_path=xnat_project_path,
        g_local_workdir_path=root_dir,
        g_pymipl_dir=pymipl_path,
    )

    print(f"global vars:{global_vars}")
    wa.set_logger()
    os.environ["XNAT_HOST"] = args.host
    os.environ["XNAT_USER"] = args.user
    os.environ["XNAT_PASS"] = args.password

    for scan in scans:
        dt = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        job = wa.populate_job_fields("jupyter", global_vars, workflow_id, scan, scan_key="StructScan")
        job["job_struct_path"] = job["job_scan_context"] / scan["StructScan"] / "DICOM"
        job_yaml = Path(__file__).with_name("main_job.yaml")

        with open(job_yaml, "r") as f:
            job_steps = yaml.safe_load(f)
        job["steps"] = job_steps.get("steps", job_steps)

        local_job_dir = local_workdir_path / "jobs" / job["job_id"]
        job_file_yaml = local_job_dir / "job.yaml"
        local_job_dir.mkdir(parents=True, exist_ok=True)

        with open(job_file_yaml, "w") as f:
            yaml.safe_dump(wa.paths_to_str(job), f, sort_keys=False)

        batch_file = root_dir / f"batch_{dt}.sh"
        with open(batch_file, "w") as f:
            f.write("#!/bin/bash\n")

        wa.workflow_to_batch(job, global_vars, batch_file)
        batch_file.chmod(0o755)
        print(f"Written {batch_file}")

        result = subprocess.run(["bash", str(batch_file)], check=False)
        if result.returncode != 0:
            raise RuntimeError(f"Batch file failed with exit code {result.returncode}: {batch_file}")
        print(f"Completed {batch_file}")

if __name__ == "__main__":
    main()
