import os
import sys
import re
import math
import glob
import shutil
import tempfile
import subprocess
import argparse
from astropy.io import fits
import numpy as np

def get_default_paths():
    if sys.platform == "win32":
        siril = r"C:\Program Files\Siril\bin\siril-cli.exe"
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        graxpert = os.path.join(local_app_data, "Programs", "GraXpert", "GraXpert.exe") if local_app_data else r"C:\Program Files\GraXpert\GraXpert.exe"
    elif sys.platform == "darwin":
        siril = "/Applications/Siril.app/Contents/MacOS/siril-cli"
        graxpert = "/Applications/GraXpert.app/Contents/MacOS/GraXpert"
    else:
        siril = shutil.which("siril-cli") or "siril-cli"
        graxpert = shutil.which("graxpert") or "graxpert"
    return siril, graxpert

def get_siril_version(siril_path):
    """Detects installed Siril version to adjust script syntax compatibility."""
    try:
        cmd = [siril_path, "--version"]
        if sys.platform.startswith("linux"):
            cmd = ["xvfb-run", "-a"] + cmd
        res = subprocess.run(cmd, capture_output=True, text=True)
        out = res.stdout + res.stderr
        match = re.search(r"siril\s+v?(\d+\.\d+\.\d+)", out, re.IGNORECASE)
        if match:
            v_str = match.group(1)
            parts = [int(p) for p in v_str.split(".")]
            return tuple(parts)
    except Exception:
        pass
    return (1, 2, 0)

# Offline-first location name mapping
OFFLINE_LOCATIONS = [
    {"lat": 51.4572, "lon": -0.0697, "name": "Greater_London"},
    {"lat": 50.1800, "lon": -5.3460, "name": "Gwinear_Gwithian"},
    {"lat": 52.8060, "lon": -4.5030, "name": "Llanengan"},
]

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000.0  # Earth's radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def clean_name(name):
    if not name:
        return ""
    cleaned = re.sub(r"[^a-zA-Z0-9\s_-]", "", name)
    cleaned = re.sub(r"[\s-]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned.strip("_")

def get_location_name(lat, lon):
    for loc in OFFLINE_LOCATIONS:
        if haversine_distance(lat, lon, loc["lat"], loc["lon"]) <= 5000.0:
            return loc["name"]
    return None

def parse_fits_target_coords(filepath):
    """Extracts target name, RA, and Dec coordinates from a FITS header."""
    target_name, ra_deg, dec_deg = None, None, None
    try:
        with fits.open(filepath, readonly=True) as hdul:
            header = hdul[0].header
            target_name = header.get("OBJECT", header.get("TARGET", None))
            
            ra_val = header.get("RA", header.get("OBJCTRA", None))
            dec_val = header.get("DEC", header.get("OBJCTDEC", None))
            
            if ra_val is not None:
                try:
                    ra_deg = float(ra_val)
                except ValueError:
                    parts = re.split(r"[\s:]+", str(ra_val).strip())
                    if len(parts) >= 3:
                        h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
                        ra_deg = (h + m/60.0 + s/3600.0) * 15.0
                        
            if dec_val is not None:
                try:
                    dec_deg = float(dec_val)
                except ValueError:
                    parts = re.split(r"[\s:]+", str(dec_val).strip())
                    if len(parts) >= 3:
                        sign = -1.0 if str(dec_val).strip().startswith("-") else 1.0
                        d, m, s = abs(float(parts[0])), float(parts[1]), float(parts[2])
                        dec_deg = sign * (d + m/60.0 + s/3600.0)
    except Exception as e:
        print(f"Warning: Failed to extract target coordinates from header: {e}")
        
    return target_name, ra_deg, dec_deg

def format_exposure(exp):
    if exp is None:
        return "Unknown_Exposure"
    try:
        val = float(exp)
        if val.is_integer():
            return f"{int(val)}s"
        return f"{val}s"
    except Exception:
        return "Unknown_Exposure"

def safe_link(src, dst):
    """Creates a hard link from src to dst. Falls back to copy if link fails."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except Exception:
        shutil.copy2(src, dst)

def run_siril(script_content, working_dir, siril_path):
    """Writes and executes a temporary Siril script in the working directory."""
    script_path = os.path.join(working_dir, "temp_run.ssf")
    with open(script_path, "w") as f:
        f.write(script_content)
        
    cmd = [siril_path, "-s", script_path, "-d", working_dir]
    if sys.platform.startswith("linux"):
        cmd = ["xvfb-run", "-a"] + cmd
        
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Clean up temporary script
    if os.path.exists(script_path):
        os.remove(script_path)
        
    return result

def run_graxpert(input_file, output_file, graxpert_path):
    """Runs GraXpert background extraction CLI on an input file, with smart border masking."""
    temp_input = None
    temp_output = None
    has_borders = False
    
    try:
        with fits.open(input_file, memmap=False) as hdul:
            data = hdul[0].data
            header = hdul[0].header
            
            # Check if there are zero pixels indicating black borders from mosaic alignment
            if data is not None and np.any(data == 0.0):
                has_borders = True
                print("    [GraXpert] Mosaic borders detected. Applying smart masking...")
                
                # Copy data
                masked_data = data.copy()
                mask = (data == 0.0)
                
                if len(data.shape) == 3:  # RGB FITS: (channels, height, width)
                    for c in range(data.shape[0]):
                        channel_data = data[c]
                        active_pixels = channel_data[(channel_data != 0.0) & (~np.isnan(channel_data))]
                        median_val = np.nanmedian(active_pixels) if active_pixels.size > 0 else 0.0
                        masked_data[c][mask[c]] = median_val
                else:  # Monochrome FITS: (height, width)
                    active_pixels = data[(data != 0.0) & (~np.isnan(data))]
                    median_val = np.nanmedian(active_pixels) if active_pixels.size > 0 else 0.0
                    masked_data[mask] = median_val
                
                # Write to temp file
                temp_input = input_file.replace(".fit", "_gx_temp_in.fit").replace(".fits", "_gx_temp_in.fits")
                fits.writeto(temp_input, masked_data, header, overwrite=True)
    except Exception as e:
        print(f"    [GraXpert] Warning during FITS header inspection: {e}")
        has_borders = False

    # Determine which input file to run GraXpert on
    file_to_process = temp_input if has_borders else input_file
    output_base, _ = os.path.splitext(output_file)
    temp_output = output_base + "_gx_temp_out.fits"
    
    # Determine if image is monochrome by reading the actual file shape
    try:
        with fits.open(file_to_process, memmap=False) as hdul_check:
            is_mono = (hdul_check[0].data is not None and hdul_check[0].data.ndim == 2)
    except Exception:
        is_mono = False
    
    cmd = [
        graxpert_path,
        "-cli",
        "-cmd", "background-extraction",
        file_to_process,
        "-output", output_base + "_gx_temp_out"
    ]
    if is_mono:
        cmd.extend(["-layer", "0"])
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Check if GraXpert succeeded and produced the output
    generated_output = temp_output
    if not os.path.exists(generated_output):
        # Try finding any file that starts with the base name
        if os.path.exists(os.path.dirname(output_file)):
            for f in os.listdir(os.path.dirname(output_file)):
                if f.startswith(os.path.basename(output_base) + "_gx_temp_out"):
                    generated_output = os.path.join(os.path.dirname(output_file), f)
                    break
                    
    if os.path.exists(generated_output):
        if has_borders:
            # Restore the black borders on the processed output
            try:
                with fits.open(generated_output, memmap=False) as hdul_out:
                    data_out = hdul_out[0].data
                    header_out = hdul_out[0].header
                    
                    with fits.open(input_file, memmap=False) as hdul_in:
                        mask = (hdul_in[0].data == 0.0)
                        
                    data_out[mask] = 0.0
                    fits.writeto(output_file, data_out, header_out, overwrite=True)
                
                # Delete generated output (temp file)
                try:
                    os.remove(generated_output)
                except Exception as del_err:
                    print(f"    [GraXpert] Non-fatal error deleting temp output file: {del_err}")
            except Exception as e:
                print(f"    [GraXpert] Error restoring borders: {e}")
                # Fallback to rename
                if os.path.exists(output_file):
                    os.remove(output_file)
                os.rename(generated_output, output_file)
        else:
            if generated_output != output_file:
                if os.path.exists(output_file):
                    os.remove(output_file)
                os.rename(generated_output, output_file)
                
        # Clean up temp input file
        if temp_input and os.path.exists(temp_input):
            try:
                os.remove(temp_input)
            except Exception as del_err:
                print(f"    [GraXpert] Non-fatal error deleting temp input file: {del_err}")
        return True
        
    print(f"Error: GraXpert did not produce expected output file. Stderr:\n{result.stderr}")
    if temp_input and os.path.exists(temp_input):
        try:
            os.remove(temp_input)
        except Exception as del_err:
            print(f"    [GraXpert] Non-fatal error deleting temp input file: {del_err}")
    return False

def hdr_blend(short_exp_path, long_exp_path, output_path, siril_path, threads, transition_low=0.6, transition_high=0.85):
    """Blends a short-exposure stack with a long-exposure stack using luminance-based HDR masking.
    
    Registers short_exp to long_exp first if dimensions mismatch.
    """
    print(f"    [HDR] Registering & blending short exposure ({os.path.basename(short_exp_path)}) with long exposure ({os.path.basename(long_exp_path)})...")
    
    hdr_work_dir = os.path.join(os.path.dirname(short_exp_path), "hdr_temp")
    os.makedirs(os.path.join(hdr_work_dir, "lights"), exist_ok=True)
    os.makedirs(os.path.join(hdr_work_dir, "process"), exist_ok=True)
    
    # Hard link images for Siril registration
    safe_link(long_exp_path, os.path.join(hdr_work_dir, "lights", "img_00001.fit"))
    safe_link(short_exp_path, os.path.join(hdr_work_dir, "lights", "img_00002.fit"))
    
    reg_ssf = (
        "requires 1.2.0\n"
        f"setcpu {threads}\n"
        "cd lights\n"
        "convert img -out=../process\n"
        "cd ../process\n"
        "register img_ -2pass\n"
        "seqapplyreg img_ -framing=max\n"
        "close\n"
    )
    
    run_siril(reg_ssf, hdr_work_dir, siril_path)
    
    aligned_long = os.path.join(hdr_work_dir, "process", "r_img_00001.fit")
    aligned_short = os.path.join(hdr_work_dir, "process", "r_img_00002.fit")
    
    if not os.path.exists(aligned_short) or not os.path.exists(aligned_long):
        # Fallback to direct read if Siril alignment didn't produce files
        aligned_short = short_exp_path
        aligned_long = long_exp_path

    with fits.open(aligned_short, memmap=False) as hdul_short:
        data_short = hdul_short[0].data.astype(np.float32)
        
    with fits.open(aligned_long, memmap=False) as hdul_long:
        data_long = hdul_long[0].data.astype(np.float32)
        header_long = hdul_long[0].header
    
    # If dimensions mismatch, resample short image to long image geometry using interpolation
    if data_short.shape != data_long.shape:
        try:
            from scipy.ndimage import zoom
            print(f"    [HDR] Resampling short exposure array {data_short.shape} to target {data_long.shape}...")
            zoom_factors = [l / s for s, l in zip(data_short.shape, data_long.shape)]
            data_short = zoom(data_short, zoom_factors, order=1)
        except Exception as ze:
            print(f"    [HDR] Warning: Resampling failed: {ze}. Using long exposure only.")
            shutil.copy2(long_exp_path, output_path)
            if os.path.exists(hdr_work_dir):
                shutil.rmtree(hdr_work_dir)
            return False

    # Clean any NaNs in input arrays
    data_short = np.nan_to_num(data_short, nan=0.0)
    data_long = np.nan_to_num(data_long, nan=0.0)

    # Normalize both to [0, 1] range for blending
    max_short = np.max(data_short) if np.max(data_short) > 0 else 1.0
    max_long = np.max(data_long) if np.max(data_long) > 0 else 1.0
    
    norm_short = data_short / max_short
    norm_long = data_long / max_long
    
    # Build luminance from the long-exposure image
    if len(data_long.shape) == 3:  # RGB: (channels, h, w)
        luminance = np.mean(norm_long, axis=0)
    else:  # Mono: (h, w)
        luminance = norm_long
    
    midpoint = (transition_low + transition_high) / 2.0
    steepness = 15.0 / max(transition_high - transition_low, 0.01)
    mask = 1.0 / (1.0 + np.exp(-steepness * (luminance - midpoint)))
    
    if len(data_long.shape) == 3:
        mask = mask[np.newaxis, :, :]
    
    blended = norm_long * (1.0 - mask) + norm_short * mask
    blended = blended * max_long
    
    # Replace any NaNs generated during calculation and preserve black borders
    blended = np.nan_to_num(blended, nan=0.0)
    both_zero = (data_short == 0.0) & (data_long == 0.0)
    blended[both_zero] = 0.0
    
    fits.writeto(output_path, blended, header_long, overwrite=True)
    if os.path.exists(hdr_work_dir):
        shutil.rmtree(hdr_work_dir)
    print(f"    [HDR] Saved HDR blend to: {os.path.basename(output_path)}")
    return True

def parse_and_cull(seq_file_path, batch_raw_files, main_node_lights_dir):
    """Parses a Siril sequence file to find and delete low-quality frames."""
    if not os.path.exists(seq_file_path):
        print(f"Warning: Sequence file {seq_file_path} not found. Skipping culling.")
        return []
        
    with open(seq_file_path, "r") as f:
        lines = f.readlines()
        
    selected_flags = {}
    frame_stats = {}
    
    # Parse image selection and registration metrics
    for line in lines:
        line = line.strip()
        if line.startswith("I "):
            parts = line.split()
            idx = int(parts[1])
            sel = int(parts[2])
            selected_flags[idx] = (sel == 1)
        elif line.startswith("R1 "):
            # Format: R1 fwhm_x fwhm_y roundness ? noise star_count ...
            parts = line.split()
            # Index is determined by position (we'll count them)
            # Find which index this refers to
            idx = len(frame_stats) + 1
            try:
                fwhm_x = float(parts[1])
                fwhm_y = float(parts[2])
                roundness = float(parts[3])
                star_count = int(parts[6])
                frame_stats[idx] = {
                    "fwhm": (fwhm_x + fwhm_y) / 2.0,
                    "roundness": roundness,
                    "star_count": star_count
                }
            except Exception as e:
                print(f"Warning: Failed to parse R1 line for frame {idx}: {e}")
                
    # Calculate medians of the registered frames
    good_fwhms = [info["fwhm"] for idx, info in frame_stats.items() if info["fwhm"] > 0 and selected_flags.get(idx, True)]
    good_rounds = [info["roundness"] for idx, info in frame_stats.items() if info["roundness"] > 0 and selected_flags.get(idx, True)]
    good_stars = [info["star_count"] for idx, info in frame_stats.items() if info["star_count"] > 0 and selected_flags.get(idx, True)]
    
    median_fwhm = np.median(good_fwhms) if good_fwhms else 3.0
    median_round = np.median(good_rounds) if good_rounds else 0.8
    median_stars = np.median(good_stars) if good_stars else 20.0
    
    print(f"Batch Medians -> FWHM: {median_fwhm:.2f} px, Roundness: {median_round:.2f}, Stars: {median_stars:.1f}")
    
    culled_indices = []
    culled_files = []
    
    # Cullen/Selection update loop
    new_lines = []
    for line in lines:
        line_strip = line.strip()
        if line_strip.startswith("I "):
            parts = line_strip.split()
            idx = int(parts[1])
            
            # Map index back to file name
            filename = batch_raw_files[idx - 1]
            stats = frame_stats.get(idx, None)
            is_good = selected_flags.get(idx, True)
            reason = ""
            
            if not is_good:
                reason = "Failed registration"
            elif stats:
                if stats["star_count"] < 8:
                    is_good = False
                    reason = f"Extremely low star count ({stats['star_count']} < 8)"
                elif stats["star_count"] < 0.5 * median_stars:
                    is_good = False
                    reason = f"Low star count (clouds?) ({stats['star_count']} < {0.5 * median_stars:.1f})"
                elif stats["fwhm"] > 1.5 * median_fwhm:
                    is_good = False
                    reason = f"High FWHM (blur) ({stats['fwhm']:.2f} > {1.5 * median_fwhm:.2f})"
                elif stats["roundness"] < 0.65:
                    is_good = False
                    reason = f"Elongated stars (trailing) ({stats['roundness']:.2f} < 0.65)"
            
            if not is_good:
                culled_indices.append(idx)
                culled_files.append(filename)
                parts[2] = "0"
                new_lines.append(" ".join(parts) + "\n")  # Deselect in sequence, preserving dimensions/metadata
                print(f"  [CULLED] {filename} -> {reason}")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
            
    # Rewrite the sequence file with updated selections
    with open(seq_file_path, "w") as f:
        f.writelines(new_lines)
        
    # Delete bad raw FITS files from the folder node permanently to free up disk space
    for filename in culled_files:
        raw_path = os.path.join(main_node_lights_dir, filename)
        if os.path.exists(raw_path):
            try:
                os.remove(raw_path)
                print(f"  [DELETED RAW] {filename}")
            except Exception as e:
                print(f"  [ERROR DELETING RAW] {filename}: {e}")
                
    return culled_files

def main():
    default_siril, default_graxpert = get_default_paths()
    
    parser = argparse.ArgumentParser(description="Ultra-optimized Astrophotography Stacking Pipeline")
    parser.add_argument("--src", default=os.path.expanduser("~/Astrophotography/M31/lights"), help="Source directory with raw FITS files")
    parser.add_argument("--dest", default=os.path.expanduser("~/Astrophotography/M31/lights_sorted"), help="Destination folder for sorted and processed files")
    parser.add_argument("--batch-size", type=int, default=200, help="Number of files to process per sub-batch (default: 200)")
    parser.add_argument("--feather-amount", type=int, default=20, help="Feather amount in pixels (default: 20)")
    parser.add_argument("--siril-path", default=default_siril, help="Path to siril-cli")
    parser.add_argument("--graxpert-path", default=default_graxpert, help="Path to GraXpert")
    parser.add_argument("--threshold", type=float, default=1000.0, help="Distance threshold in meters for location clustering")
    parser.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 4) // 2), help="Number of CPU threads to use in Siril")
    parser.add_argument("--clean", action="store_true", help="Clean destination directory before running")
    parser.add_argument("--mosaic", action="store_true", help="Stack as a mosaic (uses maximum framing and stack maximization in Siril)")
    parser.add_argument("--drizzle", type=float, choices=[1.0, 2.0], default=None, help="Drizzle scale (1.0 or 2.0) to use in Siril")
    parser.add_argument("--check", action="store_true", help="Run a pre-flight dependency check and exit")
    
    args = parser.parse_args()
    
    # Pre-flight Check Logic
    siril_ok = os.path.exists(args.siril_path) if args.siril_path else False
    graxpert_ok = os.path.exists(args.graxpert_path) if args.graxpert_path else False
    
    if args.check:
        import json
        print(json.dumps({
            "os": sys.platform,
            "siril": {"path": args.siril_path, "ok": siril_ok},
            "graxpert": {"path": args.graxpert_path, "ok": graxpert_ok}
        }))
        sys.exit(0)
        
    if not siril_ok or not graxpert_ok:
        print("=================================================================")
        print("                     PRE-FLIGHT CHECK FAILED                     ")
        print("=================================================================")
        if not siril_ok:
            print(f"[X] Siril-cli not found at: {args.siril_path}")
        if not graxpert_ok:
            print(f"[X] GraXpert not found at: {args.graxpert_path}")
        print("Please verify the paths or install the required software.")
        print("=================================================================")
        sys.exit(1)
    
    if args.mosaic and args.feather_amount == 20:
        args.feather_amount = 150
    
    if args.clean and os.path.exists(args.dest):
        print(f"Cleaning destination root directory: {args.dest}")
        try:
            shutil.rmtree(args.dest)
        except Exception as e:
            print(f"Warning: Failed to clean destination directory: {e}")
    
    print("=================================================================")
    print("        ULTRA-OPTIMIZED ASTROPHOTOGRAPHY STACKING PIPELINE       ")
    print("=================================================================")
    print(f"Source Directory:      {args.src}")
    print(f"Destination Root:      {args.dest}")
    print(f"Sub-Batch size:        {args.batch_size}")
    print(f"Feather Width:         {args.feather_amount} px")
    print(f"Siril CPU Threads:     {args.threads}")
    print(f"Clean Destination:     {args.clean}")
    print(f"Mosaic Mode:           {args.mosaic}")
    print(f"Drizzle Mode:          {args.drizzle if args.drizzle else 'Disabled'}")
    print("=================================================================\n")
    
    # ---------------------------------------------------------
    # STEP 1: Organize Raw Files using Hard Links (0 bytes space)
    # ---------------------------------------------------------
    print("Step 1: Organizing raw files into sorted folder nodes...")
    if not os.path.exists(args.src):
        print(f"Error: Source directory '{args.src}' does not exist.")
        sys.exit(1)
        
    raw_files = sorted(glob.glob(os.path.join(args.src, "*.fit")) + glob.glob(os.path.join(args.src, "*.fits")))
    print(f"Found {len(raw_files)} raw FITS files.")
    
    clusters = {} # lat_lon_key -> name
    
    # Target Auto-Detection State
    detected_target_name = None
    detected_ra_deg = None
    detected_dec_deg = None

    for filepath in raw_files:
        filename = os.path.basename(filepath)
        
        # Read header keys
        lat, lon, exp = None, None, None
        try:
            with fits.open(filepath, readonly=True) as hdul:
                header = hdul[0].header
                lat = header.get("SITELAT", None)
                lon = header.get("SITELONG", None)
                exp = header.get("EXPTIME", header.get("EXPOSURE", None))
                
                if detected_ra_deg is None or detected_dec_deg is None:
                    tname, ra_d, dec_d = parse_fits_target_coords(filepath)
                    if ra_d is not None and dec_d is not None:
                        detected_target_name = tname
                        detected_ra_deg = ra_d
                        detected_dec_deg = dec_d
        except Exception as e:
            print(f"Warning: Failed to read FITS header for {filename}: {e}")
            continue
            
        # Determine Location Directory
        if lat is None or lon is None:
            loc_dir = "Unknown_Location"
        else:
            try:
                lat = float(lat)
                lon = float(lon)
                # Find matching cluster
                matched = False
                for (clat, clon), name in clusters.items():
                    if haversine_distance(lat, lon, clat, clon) <= args.threshold:
                        loc_dir = name
                        matched = True
                        break
                if not matched:
                    # Resolve name
                    offline_name = get_location_name(lat, lon)
                    coord_suffix = f"{lat:.4f}_{lon:.4f}"
                    if offline_name:
                        loc_dir = f"{offline_name}_Loc_{coord_suffix}"
                    else:
                        loc_dir = f"Loc_{coord_suffix}"
                    clusters[(lat, lon)] = loc_dir
            except Exception:
                loc_dir = "Unknown_Location"
                
        # Determine Exposure Directory
        exp_dir = format_exposure(exp)
        
        # Create hard link to destination
        target_path = os.path.join(args.dest, loc_dir, exp_dir, "lights", filename)
        safe_link(filepath, target_path)
        
    print("Files sorted successfully with 0 duplicate space.\n")
    
    # ---------------------------------------------------------
    # STEP 2: Sequential Node Stacking & Culling
    # ---------------------------------------------------------
    print("Step 2: Starting sequential folder node stacking and culling...")
    # Find all location/exposure subdirectories containing a 'lights' folder
    node_folders = []
    for root, dirs, files in os.walk(args.dest):
        if "lights" in dirs:
            # Check if there are fits files in lights
            lights_path = os.path.join(root, "lights")
            lights_files = glob.glob(os.path.join(lights_path, "*.fit")) + glob.glob(os.path.join(lights_path, "*.fits"))
            if len(lights_files) >= 3:
                node_folders.append(root)
                
    print(f"Found {len(node_folders)} folder nodes to stack.")
    
    node_stacks = []
    
    for node_dir in node_folders:
        rel_node = os.path.relpath(node_dir, args.dest)
        print(f"\nProcessing Node: {rel_node}")
        
        lights_dir = os.path.join(node_dir, "lights")
        all_lights = sorted(glob.glob(os.path.join(lights_dir, "*.fit")) + glob.glob(os.path.join(lights_dir, "*.fits")))
        total_lights = len(all_lights)
        print(f"Total frames in node: {total_lights}")
        
        # Split into sub-batches to conserve storage
        sub_stacks = []
        num_batches = math.ceil(total_lights / args.batch_size)
        
        for batch_idx in range(num_batches):
            start = batch_idx * args.batch_size
            end = min(start + args.batch_size, total_lights)
            batch_files = all_lights[start:end]
            
            print(f"  -> Processing batch {batch_idx + 1}/{num_batches} (Frames {start + 1} to {end})...")
            
            scratch_root = os.path.join(tempfile.gettempdir(), "astro_scratch")
            batch_dir = os.path.join(scratch_root, f"batch_{batch_idx}")
            batch_lights_dir = os.path.join(batch_dir, "lights")
            batch_process_dir = os.path.join(batch_dir, "process")
            
            # Recreate batch directories in fast local temp space
            if os.path.exists(batch_dir):
                shutil.rmtree(batch_dir, ignore_errors=True)
            os.makedirs(batch_lights_dir, exist_ok=True)
            os.makedirs(batch_process_dir, exist_ok=True)
            
            # Hard link this batch's files into batch_lights_dir (0 bytes)
            batch_filenames = []
            for filepath in batch_files:
                filename = os.path.basename(filepath)
                batch_filenames.append(filename)
                safe_link(filepath, os.path.join(batch_lights_dir, filename))
                
            # --- SSF SCRIPT 1: REGISTER ---
            convert_debayer = "" if args.drizzle else " -debayer"
            if args.mosaic or args.drizzle:
                drizzle_flag = " -drizzle" if args.drizzle else ""
                scale_flag = " -scale=0.5" if args.drizzle == 1.0 else ""
                register_ssf = (
                    "requires 1.2.0\n"
                    f"setcpu {args.threads}\n"
                    "cd lights\n"
                    f"convert light{convert_debayer} -out=../process\n"
                    "cd ../process\n"
                    "register light_ -2pass\n"
                    f"seqapplyreg light_ -framing=max{drizzle_flag}{scale_flag}\n"
                    "close\n"
                )
            else:
                register_ssf = (
                    "requires 1.2.0\n"
                    f"setcpu {args.threads}\n"
                    "cd lights\n"
                    f"convert light{convert_debayer} -out=../process\n"
                    "cd ../process\n"
                    "register light_ -2pass\n"
                    "seqapplyreg light_\n"
                    "close\n"
                )
            
            print("    Running registration...")
            reg_res = run_siril(register_ssf, batch_dir, args.siril_path)
            if reg_res.returncode != 0:
                print(f"    Warning: Registration failed for batch {batch_idx}. Stderr:\n{reg_res.stderr}")
                # Clean up batch and continue
                shutil.rmtree(batch_dir)
                continue
                
            # --- CULLING ---
            seq_prefix = "r_light_"
            print("    Analyzing sequence statistics for culling...")
            seq_path = os.path.join(batch_process_dir, f"{seq_prefix}.seq")
            parse_and_cull(seq_path, batch_filenames, lights_dir)
            
            feather_opt = f" -feather={args.feather_amount}" if args.mosaic else ""
            stack_opt = " -overlap_norm -maximize" if args.mosaic else ""
            siril_ver = get_siril_version(args.siril_path)
            weight_opts = " -weight=wfwhm -32b" if siril_ver >= (1, 3, 0) else ""
            stack_ssf = (
                "requires 1.2.0\n"
                f"setcpu {args.threads}\n"
                "cd process\n"
                f"stack {seq_prefix} rej 3 3 -norm=addscale -output_norm -rgb_equal{weight_opts}{feather_opt}{stack_opt} -out=stacked\n"
                "load stacked\n"
                "mirrorx -bottomup\n"
                "save ../sub_stack\n"
                "close\n"
            )
            
            print("    Stacking batch...")
            stack_res = run_siril(stack_ssf, batch_dir, args.siril_path)
            if stack_res.returncode != 0:
                print(f"    Warning: Stacking failed for batch {batch_idx}. Stderr:\n{stack_res.stderr}")
                shutil.rmtree(batch_dir)
                continue
                
            # Save and apply per-tile GraXpert background extraction on the sub-stack
            sub_stack_raw = os.path.join(batch_dir, "sub_stack.fit")
            sub_stack_dest = os.path.join(node_dir, f"sub_stack_{batch_idx}.fit")
            if os.path.exists(sub_stack_raw):
                print("    Applying per-tile GraXpert background extraction to sub-stack...")
                gx_sub_ok = run_graxpert(sub_stack_raw, sub_stack_dest, args.graxpert_path)
                if not gx_sub_ok:
                    if os.path.exists(sub_stack_dest):
                        os.remove(sub_stack_dest)
                    os.rename(sub_stack_raw, sub_stack_dest)
                sub_stacks.append(sub_stack_dest)
                
            # Delete batch files immediately to recover disk space!
            shutil.rmtree(batch_dir)
            print("    Cleaned up batch intermediate files.")
            
        # Combine sub-stacks into a single stacked_result.fit
        if not sub_stacks:
            print(f"Error: No sub-stacks generated for node {rel_node}. Skipping.")
            continue
            
        stacked_result = os.path.join(node_dir, "stacked_result.fit")
        if len(sub_stacks) == 1:
            if os.path.exists(stacked_result):
                os.remove(stacked_result)
            os.rename(sub_stacks[0], stacked_result)
        else:
            print("  -> Combining sub-stacks into a final stack for this node...")
            final_stack_dir = os.path.join(tempfile.gettempdir(), "astro_scratch", "final_node_stack")
            fs_lights_dir = os.path.join(final_stack_dir, "lights")
            fs_process_dir = os.path.join(final_stack_dir, "process")
            
            if os.path.exists(final_stack_dir):
                shutil.rmtree(final_stack_dir, ignore_errors=True)
            os.makedirs(fs_lights_dir, exist_ok=True)
            os.makedirs(fs_process_dir, exist_ok=True)
            
            # Hard link sub-stacks as master_00001.fit, master_00002.fit
            for idx, ss_path in enumerate(sub_stacks):
                safe_link(ss_path, os.path.join(fs_lights_dir, f"master_{idx + 1:05d}.fit"))
                
            siril_ver = get_siril_version(args.siril_path)
            weight_opts = " -weight=wfwhm -32b" if siril_ver >= (1, 3, 0) else ""
            if args.mosaic:
                fs_ssf = (
                    "requires 1.2.0\n"
                    f"setcpu {args.threads}\n"
                    "cd lights\n"
                    "convert master -out=../process\n"
                    "cd ../process\n"
                    "register master_ -2pass -minpairs=5\n"
                    "seqapplyreg master_ -framing=max\n"
                    f"stack r_master_ rej 3 3 -norm=addscale -output_norm -rgb_equal{weight_opts} -feather={args.feather_amount} -overlap_norm -maximize -out=stacked\n"
                    "load stacked\n"
                    "mirrorx -bottomup\n"
                    "save ../../stacked_result\n"
                    "close\n"
                )
            else:
                fs_ssf = (
                    "requires 1.2.0\n"
                    f"setcpu {args.threads}\n"
                    "cd lights\n"
                    "convert master -out=../process\n"
                    "cd ../process\n"
                    "register master_ -2pass -minpairs=5\n"
                    "seqapplyreg master_\n"
                    f"stack r_master_ rej 3 3 -norm=addscale -output_norm -rgb_equal{weight_opts} -out=stacked\n"
                    "load stacked\n"
                    "mirrorx -bottomup\n"
                    "save ../../stacked_result\n"
                    "close\n"
                )
            
            fs_res = run_siril(fs_ssf, final_stack_dir, args.siril_path)
            if fs_res.returncode != 0:
                print(f"Error: Final node merge failed. Stderr:\n{fs_res.stderr}")
                # Clean up and skip node
                shutil.rmtree(final_stack_dir)
                for ss in sub_stacks:
                    if os.path.exists(ss):
                        os.remove(ss)
                continue
                
            # Clean up temporary folders and sub-stacks
            shutil.rmtree(final_stack_dir)
            for ss in sub_stacks:
                if os.path.exists(ss):
                    os.remove(ss)
                    
        # Apply GraXpert AI Background Extraction on the node's stack
        print("  -> Applying GraXpert AI background extraction...")
        graxpert_output = os.path.join(node_dir, "stacked_result_GraXpert.fits")
        gx_ok = run_graxpert(stacked_result, graxpert_output, args.graxpert_path)
        if gx_ok:
            node_stacks.append(graxpert_output)
            # Delete unextracted stacked_result
            if os.path.exists(stacked_result):
                os.remove(stacked_result)
            print(f"  -> Saved background-extracted stack: stacked_result_GraXpert.fits")
        else:
            print("  -> Warning: GraXpert failed. Keeping unextracted stacked_result.fit.")
            node_stacks.append(stacked_result)
            
    # ---------------------------------------------------------
    # STEP 2.5: HDR Blend (combine exposure times per location)
    # ---------------------------------------------------------
    # Group node stacks by location (parent of the exposure folder)
    # node_stacks paths look like: <dest>/<location>/<exposure>/stacked_result_GraXpert.fits
    location_groups = {}
    for ns_path in node_stacks:
        # The exposure dir is the parent, the location dir is the grandparent
        exp_dir = os.path.dirname(ns_path)
        loc_dir = os.path.dirname(exp_dir)
        exp_name = os.path.basename(exp_dir)
        
        if loc_dir not in location_groups:
            location_groups[loc_dir] = {}
        location_groups[loc_dir][exp_name] = ns_path
    
    hdr_stacks = []
    for loc_dir, exp_stacks in location_groups.items():
        loc_name = os.path.basename(loc_dir)
        if len(exp_stacks) > 1:
            print(f"\nStep 2.5: HDR blending exposures for {loc_name}...")
            print(f"  Available exposures: {', '.join(sorted(exp_stacks.keys()))}")
            
            # Sort exposures by numeric value (shortest first)
            def _exp_sort_key(k):
                try:
                    return float(k.replace('s', ''))
                except ValueError:
                    return float('inf')  # Unknown_Exposure sorts last
            sorted_exps = sorted(exp_stacks.keys(), key=_exp_sort_key)
            
            # Start with the longest exposure as the base
            long_exp_key = sorted_exps[-1]
            result_path = exp_stacks[long_exp_key]
            
            # Blend in each shorter exposure (shortest first, working up)
            for short_exp_key in sorted_exps[:-1]:
                short_path = exp_stacks[short_exp_key]
                hdr_output = os.path.join(loc_dir, f"hdr_blend_{short_exp_key}_{long_exp_key}.fits")
                
                try:
                    hdr_blend(short_path, result_path, hdr_output, args.siril_path, args.threads)
                    result_path = hdr_output
                except Exception as e:
                    print(f"    [HDR] Warning: HDR blend failed: {e}. Using long exposure only.")
            
            hdr_stacks.append(result_path)
        else:
            # Only one exposure time at this location, pass through
            hdr_stacks.append(list(exp_stacks.values())[0])
    
    # ---------------------------------------------------------
    # STEP 3: Produce Final Master Stack
    # ---------------------------------------------------------
    print("\nStep 3: Stacking all session masters into a final master stack...")
    if not hdr_stacks:
        print("Error: No stacks available for final merge.")
        sys.exit(1)
        
    final_master_result = os.path.join(args.dest, "final_master_result.fit")
    
    if len(hdr_stacks) == 1:
        print("Only one location stacked. Skipping final merge.")
        shutil.copy2(hdr_stacks[0], final_master_result)
    else:
        final_dir = os.path.join(tempfile.gettempdir(), "astro_scratch", "final_master_stack")
        final_lights_dir = os.path.join(final_dir, "lights")
        final_process_dir = os.path.join(final_dir, "process")
        
        if os.path.exists(final_dir):
            shutil.rmtree(final_dir, ignore_errors=True)
        os.makedirs(final_lights_dir, exist_ok=True)
        os.makedirs(final_process_dir, exist_ok=True)
        
        # Hard link stacks as session_00001.fits...
        for idx, ns_path in enumerate(hdr_stacks):
            _, ext = os.path.splitext(ns_path)
            safe_link(ns_path, os.path.join(final_lights_dir, f"session_{idx + 1:05d}{ext}"))
            
        siril_ver = get_siril_version(args.siril_path)
        weight_opts = " -weight=wfwhm -32b" if siril_ver >= (1, 3, 0) else ""
        if args.mosaic:
            final_ssf = (
                "requires 1.2.0\n"
                f"setcpu {args.threads}\n"
                "cd lights\n"
                "convert session -debayer -out=../process\n"
                "cd ../process\n"
                "register session_ -2pass\n"
                "seqapplyreg session_ -framing=max\n"
                f"stack r_session_ rej 3 3 -norm=addscale -output_norm -rgb_equal{weight_opts} -feather={args.feather_amount} -overlap_norm -maximize -out=stacked\n"
                "load stacked\n"
                "mirrorx -bottomup\n"
                "save ../../final_master_result\n"
                "close\n"
            )
        else:
            final_ssf = (
                "requires 1.2.0\n"
                f"setcpu {args.threads}\n"
                "cd lights\n"
                "convert session -debayer -out=../process\n"
                "cd ../process\n"
                "register session_ -2pass\n"
                f"stack r_session_ rej 3 3 -norm=addscale -output_norm -rgb_equal{weight_opts} -out=stacked\n"
                "load stacked\n"
                "mirrorx -bottomup\n"
                "save ../../final_master_result\n"
                "close\n"
            )
        
        print("  Running final session stack...")
        final_res = run_siril(final_ssf, final_dir, args.siril_path)
        if final_res.returncode != 0:
            print(f"Error: Final master stacking failed. Stderr:\n{final_res.stderr}")
            shutil.rmtree(final_dir)
            sys.exit(1)
            
        # Clean up final processing dir
        shutil.rmtree(final_dir)
    
    # ---------------------------------------------------------
    # STEP 4: Photometric Color Calibration (PCC)
    # ---------------------------------------------------------
    print("\nStep 4: Applying Photometric Color Calibration...")
    coord_arg = ""
    if detected_ra_deg is not None and detected_dec_deg is not None:
        print(f"  Target coordinates auto-detected from FITS header: RA {detected_ra_deg:.4f}°, Dec {detected_dec_deg:.4f}° ({detected_target_name or 'Deep Sky Object'})")
        coord_arg = f" {detected_ra_deg:.4f},{detected_dec_deg:.4f}"
    else:
        print("  No target coordinates found in FITS header. Attempting blind plate solve...")

    pcc_ssf = (
        "requires 1.2.0\n"
        f"setcpu {args.threads}\n"
        "load final_master_result\n"
        f"platesolve{coord_arg} -force -noflip\n"
        "pcc -cat=nomad\n"
        "save final_master_result_pcc\n"
        "close\n"
    )
    pcc_result = os.path.join(args.dest, "final_master_result_pcc.fit")
    pcc_res = run_siril(pcc_ssf, args.dest, args.siril_path)
    
    if pcc_res.returncode != 0 or not os.path.exists(pcc_result):
        # Fallback to Gaia DR3 catalogue if NOMAD VizieR server is unavailable (503)
        pcc_ssf_gaia = (
            "requires 1.2.0\n"
            f"setcpu {args.threads}\n"
            "load final_master_result\n"
            f"platesolve{coord_arg} -force -noflip\n"
            "pcc -cat=gaiadr3\n"
            "save final_master_result_pcc\n"
            "close\n"
        )
        pcc_res = run_siril(pcc_ssf_gaia, args.dest, args.siril_path)
    
    if pcc_res.returncode == 0 and os.path.exists(pcc_result):
        print("  PCC applied successfully.")
        # Use PCC result for GraXpert
        pcc_input = pcc_result
        # Clean up non-PCC master
        if os.path.exists(final_master_result):
            os.remove(final_master_result)
    else:
        print(f"  Warning: PCC failed (plate solve may have not converged). Continuing without PCC.")
        print(f"  Siril stderr: {pcc_res.stderr[:500] if pcc_res.stderr else 'None'}")
        pcc_input = final_master_result
        
    # ---------------------------------------------------------
    # STEP 5: Final GraXpert Polish
    # ---------------------------------------------------------
    print("\nStep 5: Applying final GraXpert AI background extraction polish...")
    ultimate_output = os.path.join(args.dest, "final_master_result_GraXpert.fits")
    gx_master_ok = run_graxpert(pcc_input, ultimate_output, args.graxpert_path)
    
    final_master_file = ultimate_output if gx_master_ok else pcc_input
    if gx_master_ok and os.path.exists(pcc_input):
        os.remove(pcc_input)
        
    # ---------------------------------------------------------
    # STEP 6: Auto-Crop Stacking Artifacts & Vignetted Padding
    # ---------------------------------------------------------
    print("\nStep 6: Auto-cropping mosaic stacking artifacts and outer padding...")
    cropped_output = os.path.join(args.dest, "final_master_result_cropped.fits")
    try:
        with fits.open(final_master_file, memmap=False) as hdul:
            data = hdul[0].data
            header = hdul[0].header
            
            # Find non-zero pixel mask across channels, ignoring NaNs
            data = np.nan_to_num(data, nan=0.0)
            if len(data.shape) == 3:
                valid_mask = np.any(data > 0.0, axis=0)
            else:
                valid_mask = data > 0.0
                
            # Find tight bounding box of valid data
            rows = np.any(valid_mask, axis=1)
            cols = np.any(valid_mask, axis=0)
            
            if np.any(rows) and np.any(cols):
                rmin, rmax = np.where(rows)[0][[0, -1]]
                cmin, cmax = np.where(cols)[0][[0, -1]]
                
                # Trim an extra 8% border inward to remove low-overlap edge fade and vignette borders
                r_margin = int((rmax - rmin) * 0.08)
                c_margin = int((cmax - cmin) * 0.08)
                
                rmin_c = min(rmin + r_margin, rmax)
                rmax_c = max(rmax - r_margin, rmin)
                cmin_c = min(cmin + c_margin, cmax)
                cmax_c = max(cmax - c_margin, cmin)
                
                if len(data.shape) == 3:
                    cropped_data = data[:, rmin_c:rmax_c+1, cmin_c:cmax_c+1]
                else:
                    cropped_data = data[rmin_c:rmax_c+1, cmin_c:cmax_c+1]
                    
                fits.writeto(cropped_output, cropped_data, header, overwrite=True)
                print(f"  Cropped successfully to bounding box [{cmax_c-cmin_c+1}x{rmax_c-rmin_c+1}]")
                crop_final = cropped_output
            else:
                crop_final = final_master_file
    except Exception as e:
        print(f"  Warning: Auto-crop encountered an issue: {e}. Skipping crop.")
        crop_final = final_master_file

    # ---------------------------------------------------------
    # STEP 7: Star removal / Nebula Processing & Auto-Stretch
    # ---------------------------------------------------------
    print("\nStep 7: Processing Nebulosity/Stars & Exporting Display Master...")
    
    # Try running StarNet star removal if available in Siril
    starnet_ssf = (
        "requires 1.2.0\n"
        f"setcpu {args.threads}\n"
        f"load {os.path.basename(crop_final)}\n"
        "starnet -stretch -upscale\n"
        "close\n"
    )
    sn_res = run_siril(starnet_ssf, args.dest, args.siril_path)
    starless_file = os.path.join(args.dest, "starless_" + os.path.basename(crop_final))
    
    if sn_res.returncode == 0 and os.path.exists(starless_file):
        print("  [StarNet] Starless processing succeeded!")
        target_for_stretch = starless_file
    else:
        print("  [StarNet] StarNet not configured or skipped. Processing master directly.")
        target_for_stretch = crop_final

    stretch_ssf = (
        "requires 1.2.0\n"
        f"setcpu {args.threads}\n"
        f"load {os.path.basename(target_for_stretch)}\n"
        "autostretch\n"
        "save final_master_display_stretched\n"
        "close\n"
    )
    stretch_res = run_siril(stretch_ssf, args.dest, args.siril_path)
    display_stretched = os.path.join(args.dest, "final_master_display_stretched.fit")
    
    if stretch_res.returncode == 0 and os.path.exists(display_stretched):
        print(f"\nSuccess! Ultimate processing pipeline complete!")
        print(f"  1. Linear Master FITS:    {crop_final}")
        print(f"  2. Stretched Display FITS: {display_stretched}")
    else:
        print(f"\nSuccess! Ultimate processing pipeline complete!")
        print(f"  Linear Master FITS: {crop_final}")

if __name__ == "__main__":
    main()
