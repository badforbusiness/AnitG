param(
    [string]$GcpProject,
    [string]$Region = "europe-west1",
    [string]$BucketName,
    [string]$Src = "C:\Astrophotography\lemuncomet\lights",
    [string]$Dest = "C:\Astrophotography\lemuncomet\lights_sorted",
    [string]$TaskTimeout = "20m",
    [int]$Threads = 8,
    [switch]$Mosaic,
    [switch]$Clean
)

# -------------------------------------------------------------------
# BUDGET SAFETY & PRE-FLIGHT VALIDATION
# -------------------------------------------------------------------
Write-Host "====================================================="
Write-Host "   GCP Cloud Run Astrophotography Pipeline Launcher  "
Write-Host "====================================================="

# Check if gcloud CLI is installed (auto-append local install path if missing from session PATH)
if (-not (Get-Command "gcloud" -ErrorAction SilentlyContinue)) {
    $sdkBin = "$env:LocalAppData\Google\Cloud SDK\google-cloud-sdk\bin"
    if (Test-Path "$sdkBin\gcloud.cmd") {
        $env:PATH = "$sdkBin;$env:PATH"
    } else {
        Write-Error "Google Cloud SDK (gcloud CLI) is not installed or not in PATH. Please install gcloud CLI first."
        exit 1
    }
}

# Auto-detect current GCP project if not passed
if (-not $GcpProject) {
    $GcpProject = (gcloud config get-value project 2>$null)
    if (-not $GcpProject -or $GcpProject -eq "(unset)") {
        Write-Error "No GCP Project specified. Pass -GcpProject 'YOUR_PROJECT_ID' or set via 'gcloud config set project'."
        exit 1
    }
}

if (-not $BucketName) {
    $BucketName = "astro-data-$GcpProject"
}

$RepoUrl = "$Region-docker.pkg.dev/$GcpProject/astro-repo/astro-pipeline:latest"

Write-Host "GCP Project ID:  $GcpProject"
Write-Host "GCP Region:      $Region"
Write-Host "GCS Bucket:      gs://$BucketName"
Write-Host "Local Input:     $Src"
Write-Host "Local Output:    $Dest"
Write-Host "Task Timeout:    $TaskTimeout (Budget Hard-Cap)"
Write-Host "Image Tag:       $RepoUrl"
Write-Host "-----------------------------------------------------"

# -------------------------------------------------------------------
# STEP 1: Create Artifact Registry Repo if needed
# -------------------------------------------------------------------
Write-Host "[1/6] Checking Artifact Registry repository..."
gcloud artifacts repositories describe astro-repo --location=$Region --project=$GcpProject 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating Artifact Registry repository 'astro-repo' in $Region..."
    gcloud artifacts repositories create astro-repo --repository-format=docker --location=$Region --description="Astrophotography Docker Repo" --project=$GcpProject
}

# -------------------------------------------------------------------
# STEP 2: Build & Push Container to GCP Artifact Registry
# -------------------------------------------------------------------
Write-Host "[2/6] Configuring Docker authentication for GCP..."
gcloud auth configure-docker "$Region-docker.pkg.dev" --quiet

Write-Host "[2/6] Tagging and pushing container image to GCP..."
docker tag astro-pipeline:latest $RepoUrl
docker push $RepoUrl
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to push image to Artifact Registry."
    exit 1
}

# -------------------------------------------------------------------
# STEP 3: Create GCS Storage Bucket if needed
# -------------------------------------------------------------------
Write-Host "[3/6] Checking Google Cloud Storage bucket..."
gcloud storage buckets describe "gs://$BucketName" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating storage bucket gs://$BucketName in $Region..."
    gcloud storage buckets create "gs://$BucketName" --location=$Region --project=$GcpProject
}

# -------------------------------------------------------------------
# STEP 4: Upload Raw FITS files to Cloud Storage
# -------------------------------------------------------------------
Write-Host "[4/6] Uploading raw FITS files from $Src to gs://$BucketName/input/..."
gcloud storage cp "$Src\*.fit*" "gs://$BucketName/input/"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to upload FITS files to GCS bucket."
    exit 1
}

# -------------------------------------------------------------------
# STEP 5: Create & Execute Cloud Run Job with Budget Timeout Capping
# -------------------------------------------------------------------
Write-Host "[5/6] Creating & executing Cloud Run Job (Capped at $TaskTimeout)..."
$jobName = "astro-stack-run"

# Check if job exists
$jobVerb = "create"
& "$sdkBin\gcloud.cmd" run jobs describe $jobName --region=$Region --project=$GcpProject 2>$null
if ($LASTEXITCODE -eq 0) {
    $jobVerb = "update"
}

# Build Job Args
$jobArgs = @(
    "run", "jobs", $jobVerb, $jobName,
    "--image=$RepoUrl",
    "--cpu=$Threads",
    "--memory=16Gi",
    "--max-retries=0",
    "--task-timeout=$TaskTimeout",
    "--region=$Region",
    "--project=$GcpProject",
    "--add-volume=name=gcs-vol,type=cloud-storage,bucket=$BucketName",
    "--add-volume-mount=volume=gcs-vol,mount-path=/input,sub-path=input",
    "--add-volume-mount=volume=gcs-vol,mount-path=/output,sub-path=output",
    "--args=--src,/input,--dest,/output,--threads,$Threads"
)

if ($Clean) { $jobArgs += "--args=--clean" }
if ($Mosaic) { $jobArgs += "--args=--mosaic" }

# Deploy/Update the Job definition
& gcloud $jobArgs

# Execute the job and wait for completion
Write-Host "Executing Cloud Run Job '$jobName' on GCP..."
gcloud run jobs execute $jobName --region=$Region --project=$GcpProject --wait
if ($LASTEXITCODE -ne 0) {
    Write-Error "Cloud Run Job execution failed or timed out."
    exit 1
}

# -------------------------------------------------------------------
# STEP 6: Download Output Results to Local PC
# -------------------------------------------------------------------
Write-Host "[6/6] Downloading finished master FITS files to $Dest..."
if (-not (Test-Path $Dest)) {
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
}

gcloud storage cp "gs://$BucketName/output/final_master_*" "$Dest\"

Write-Host "====================================================="
Write-Host "  SUCCESS! GCP Pipeline completed and results saved: "
Write-Host "  Destination: $Dest"
Write-Host "====================================================="
