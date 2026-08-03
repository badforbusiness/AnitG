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
Launch the graphical interface:
```powershell
python gui.py
```

### Windows CLI (Direct PowerShell / CMD)
You can run the pipeline directly from PowerShell or Command Prompt without launching the GUI. The script automatically locates `siril-cli.exe` and `GraXpert.exe` in standard Windows install locations:

```powershell
python run_pipeline.py `
    --src "C:\Astrophotography\M31\lights" `
    --dest "C:\Astrophotography\M31\lights_sorted" `
    --threads 12 `
    --batch-size 200 `
    --mosaic
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

## Siril & GraXpert CLI Version Compatibility

- **Dynamic Syntax Adaptation**: `run_pipeline.py` inspects the installed Siril version at runtime (`get_siril_version()`).
- **Siril 1.3+ (Windows/macOS)**: Automatically utilizes advanced stacking flags such as `-weight=wfwhm` and `-32b`.
- **Siril 1.2.x (Linux/Docker)**: Automatically adjusts command syntax to remain compatible with standard Siril 1.2.6 packages without crashing.
- **Headless Display Handling**: On Linux/Docker, `run_pipeline.py` automatically wraps Siril CLI calls with `xvfb-run` to supply a virtual X11 display buffer, preventing GTK display errors when running without a desktop environment.

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

## GCP Deployment (Cloud Run Jobs)

An automated script `run_gcp_test.ps1` handles the full GCP Cloud Run workflow with built-in **budget safeguards** (hard 20-minute execution cap, serverless pay-per-second billing, and automatic output download):

```powershell
# Run on GCP with automated GCS upload, Cloud Run execution, and result download
powershell -ExecutionPolicy Bypass -File .\run_gcp_test.ps1 `
    -GcpProject "YOUR_PROJECT_ID" `
    -Src "C:\Astrophotography\lemuncomet\lights" `
    -Dest "C:\Astrophotography\lemuncomet\lights_sorted" `
    -TaskTimeout "20m"
```

### What `run_gcp_test.ps1` does automatically:
1. **Artifact Registry Setup**: Ensures `astro-repo` Docker repository exists in your GCP region.
2. **Container Push**: Tags & pushes your local `astro-pipeline:latest` image to GCP.
3. **GCS Bucket Setup**: Ensures Cloud Storage bucket `gs://astro-data-PROJECT_ID` exists.
4. **Data Upload**: Syncs raw FITS files from your local computer to `gs://.../input/`.
5. **Serverless Execution**: Deploys & runs a **Cloud Run Job** with GCS bucket volume mounts and a **20-minute hard budget timeout cap**.
6. **Result Download**: Automatically downloads the generated `final_master_*` FITS files directly back to your local Windows output folder.
