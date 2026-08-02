# AnitG — Astrophotography Pipeline

An automated, multi-session astrophotography stacking pipeline. Organises raw FITS files by location and exposure, registers and stacks them in batches using Siril, applies AI background extraction with GraXpert, and produces a calibrated final master stack.

## Features

- **Smart file organisation** — Groups lights by GPS location and exposure time using FITS header metadata
- **Batch stacking** — Splits large frame counts into sub-batches to conserve disk space, then merges
- **Auto frame culling** — Rejects frames with poor FWHM, elongated stars, or low star count
- **GraXpert AI background extraction** — Applied per-tile and on the final stack
- **HDR blending** — Combines short and long exposure stacks per location
- **Plate solving & PCC** — Astrometric calibration of the final master
- **Mosaic & Drizzle support** — Optional modes for wide-field or high-resolution targets
- **OS-aware** — Runs on Windows (with GUI) or headless on Linux/Docker/GCP
- **Pre-flight checks** — Validates Siril and GraXpert are accessible before processing begins

## Project Structure

```
AnitG/
├── run_pipeline.py     # Core headless pipeline (cross-platform)
├── gui.py              # Native Windows Tkinter GUI wrapper
├── Dockerfile          # Docker image for headless/cloud execution
├── run_docker.ps1      # PowerShell helper to launch Docker runs
└── .gitignore
```

## Requirements

### Windows (GUI)
- Python 3.9+
- [Siril](https://siril.org/) 1.2.0+
- [GraXpert](https://www.graxpert.com/) 3.0+
- Python packages: `astropy numpy scipy Pillow`

### Docker / Linux / GCP (Headless)
- Docker Desktop (local) or Docker Engine (cloud)
- Build and run the included `Dockerfile` — Siril and GraXpert are installed automatically

## Usage

### Windows GUI
```powershell
python gui.py
```

### Headless (Docker)
```powershell
# Build the image (one-time)
docker build -t astro-pipeline .

# Run via helper script
powershell -ExecutionPolicy Bypass -File .\run_docker.ps1 `
    -Src "C:\Astrophotography\M31\lights" `
    -Dest "C:\Astrophotography\M31\lights_sorted" `
    -Threads 12

# Or run directly with Docker
docker run --rm \
  -v /path/to/lights:/input \
  -v /path/to/output:/output \
  astro-pipeline --src /input --dest /output --threads 8
```

### Pre-flight check
```powershell
# Windows
python run_pipeline.py --check

# Docker
powershell -ExecutionPolicy Bypass -File .\run_docker.ps1 -Check
```

### Key arguments

| Argument | Default | Description |
|---|---|---|
| `--src` | `~/Astrophotography/M31/lights` | Source folder of raw FITS files |
| `--dest` | `~/Astrophotography/M31/lights_sorted` | Output folder |
| `--threads` | half of CPU count | Siril CPU threads |
| `--batch-size` | 200 | Frames per sub-batch |
| `--mosaic` | off | Enable mosaic stacking mode |
| `--drizzle` | off | Enable drizzle (1.0 or 2.0) |
| `--clean` | off | Wipe destination before running |
| `--check` | off | Pre-flight dependency check only |

## GCP Deployment

To run on Google Cloud Platform, build and push the image to Artifact Registry, then run on a Compute Engine instance or Cloud Run job:

```bash
docker build -t gcr.io/YOUR_PROJECT/astro-pipeline .
docker push gcr.io/YOUR_PROJECT/astro-pipeline

gcloud run jobs create astro-pipeline \
  --image gcr.io/YOUR_PROJECT/astro-pipeline \
  --tasks 1 --max-retries 0 \
  --args="--src,/input,--dest,/output,--threads,16"
```
