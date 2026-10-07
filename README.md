# TotalSegmentator Liver Lesion XNAT Runtime

This repository contains the XNAT runtime used to run TotalSegmentator liver-lesion segmentation on structural CT scans and upload the resulting RTSTRUCT back to XNAT.

The runtime is launched from `entrypoint.py`, which:

1. loads the XNAT session/project inputs from `/input`
2. identifies structural CT scans with existing segmentations
3. converts the selected structural DICOM series to NIfTI
4. runs `TotalSegmentator --task liver_lesions`
5. converts the generated lesion mask to DICOM RTSTRUCT
6. uploads the RTSTRUCT to the scan-level resource and the workflow output bundle to the experiment-level resource

## Workflow behavior

The job flow in `main_job.yaml` is:

1. create the scan workdir and `secondary` output folder
2. convert the structural scan to NIfTI in `scan{job_scan_id}/ct`
3. run TotalSegmentator on `ct_struct.nii.gz` and write outputs into `scan{job_scan_id}/totalseg_liver_lesions`
4. convert the generated mask at `scan{job_scan_id}/totalseg_liver_lesions/liver_lesions.nii.gz` into RTSTRUCT
5. upload the RTSTRUCT to the scan resource named `secondary`
6. upload the workflow output bundle to the experiment resource named `{g_workflow_id}`

This runtime is intended for CT structural scans in an XNAT session and is built around the `liver_lesions` task from TotalSegmentator.

## Repository layout

- `entrypoint.py`: main runtime entrypoint that discovers scans and launches jobs
- `main_job.yaml`: per-scan workflow steps executed by the runtime
- `command.json`: XNAT command specification for the container
- `totalsegmenter-xnat-example.conf`: example image-build configuration
- `totalsegmenter-xnat-local.conf`: local machine-specific build config

## Build/package usage

This repo is not a standalone application. It is the runtime source copied into a custom XNAT container image built with `pymipl/build_deploy_custom_image.sh`.

The current build config format matches the files in this repo:

```bash
REMOTE_IMAGE=mmilch01/totalseg-liver-tumor:0.01
LOCAL_IMAGE="$REMOTE_IMAGE"
DOCKER_REPO=docker.io
LOCAL_ENV_FOLDER="/opt/packages/user/env_repo"
LOCAL_ALG_FOLDER=""
LOCAL_RUNTIME_FOLDER="/home/mmilchenko/src/totalsegmenter-xnat"
ENV_VARS="USER=xnat LOGNAME=xnat"
```

## Runtime assumptions

- CT-only structural scan workflow
- TotalSegmentator task: `liver_lesions`
- output mask name: `liver_lesions.nii.gz`
- RTSTRUCT label set: `Totalseg-tumor`
- RTSTRUCT series description: `Multi-organ abdominal CT segmentation`
- scan-level upload target: `secondary`
- workflow output bundle is uploaded to the experiment resource for `TOTALSEG_LIVER_TUMOR`
