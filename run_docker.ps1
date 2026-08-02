param(
    [string]$Src = "C:\Astrophotography\M31\lights",
    [string]$Dest = "C:\Astrophotography\M31\lights_sorted",
    [int]$Threads = 12,
    [int]$BatchSize = 200,
    [int]$FeatherAmount = 150,
    [switch]$Mosaic,
    [string]$Drizzle = "0",  # Sentinel meaning disabled; pipeline accepts 1.0 or 2.0 only
    [switch]$Clean,
    [switch]$Check
)

# Auto-build the Docker image if it doesn't exist
if (-not (docker image inspect astro-pipeline 2>$null | Select-String '"Id"')) {
    Write-Host "Docker image 'astro-pipeline' not found. Building now..."
    docker build -t astro-pipeline (Split-Path -Parent $PSCommandPath)
    if ($LASTEXITCODE -ne 0) { Write-Error "Docker build failed."; exit 1 }
}

# Ensure the destination directory exists before Docker tries to mount it
if (-not (Test-Path $Dest)) {
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
}

# Convert Windows paths to Docker volume mounts
# We use absolute paths to ensure Docker can mount them
$SrcPath = Resolve-Path $Src -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path
$DestPath = Resolve-Path $Dest -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path

if (-not $SrcPath) { $SrcPath = $Src }
if (-not $DestPath) { $DestPath = $Dest }

# Build the docker run arguments
$dockerArgs = @(
    "run",
    "--rm",
    "-v", "$($SrcPath):/input",
    "-v", "$($DestPath):/output",
    "astro-pipeline",
    "--src", "/input",
    "--dest", "/output",
    "--threads", "$Threads",
    "--batch-size", "$BatchSize",
    "--feather-amount", "$FeatherAmount"
)

if ($Mosaic) { $dockerArgs += "--mosaic" }
if ($Drizzle -ne "0") { $dockerArgs += "--drizzle"; $dockerArgs += $Drizzle }
if ($Clean) { $dockerArgs += "--clean" }
if ($Check) { $dockerArgs += "--check" }

Write-Host "====================================================="
Write-Host "  Launching Headless Astrophotography Pipeline (Docker)"
Write-Host "====================================================="
Write-Host "Source: $SrcPath"
Write-Host "Destination: $DestPath"
Write-Host "Command: docker $dockerArgs"
Write-Host "-----------------------------------------------------"

# Execute the Docker container
& docker $dockerArgs
