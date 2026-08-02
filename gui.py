import os
import sys
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from astropy.io import fits
import numpy as np
from PIL import Image, ImageTk

class AstrophotographyGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Astrophotography Pipeline Control")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        
        self.pipeline_process = None
        self.pipeline_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Style
        style = ttk.Style()
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        
        # Main Frame
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- Left Panel: Controls ---
        left_panel = ttk.LabelFrame(main_frame, text="Pipeline Controls", padding="10")
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        # Source Directory
        ttk.Label(left_panel, text="Source Directory (Raw Lights):").pack(anchor=tk.W, pady=(5, 0))
        src_frame = ttk.Frame(left_panel)
        src_frame.pack(fill=tk.X, pady=(0, 10))
        self.src_var = tk.StringVar(value=os.path.normpath(os.path.expanduser("~/Astrophotography/M31/lights")))
        self.src_var.trace_add("write", self.update_dest)
        ttk.Entry(src_frame, textvariable=self.src_var, width=30).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(src_frame, text="Browse...", command=self.browse_src).pack(side=tk.RIGHT, padx=(5, 0))
        
        # Destination Directory
        ttk.Label(left_panel, text="Destination Root (Auto-generated):").pack(anchor=tk.W)
        self.dest_var = tk.StringVar(value=os.path.normpath(os.path.expanduser("~/Astrophotography/M31/lights_sorted")))
        dest_entry = ttk.Entry(left_panel, textvariable=self.dest_var, state='readonly')
        dest_entry.pack(fill=tk.X, pady=(0, 10))
        
        # Settings Grid
        settings_frame = ttk.Frame(left_panel)
        settings_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(settings_frame, text="CPU Threads:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.threads_var = tk.IntVar(value=12)
        ttk.Spinbox(settings_frame, from_=1, to=64, textvariable=self.threads_var, width=8).grid(row=0, column=1, sticky=tk.W, pady=5)
        
        ttk.Label(settings_frame, text="Batch Size:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.batch_var = tk.IntVar(value=200)
        ttk.Entry(settings_frame, textvariable=self.batch_var, width=10).grid(row=1, column=1, sticky=tk.W, pady=5)
        
        ttk.Label(settings_frame, text="Drizzle Scale:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.drizzle_var = tk.StringVar(value="1.0")
        ttk.Combobox(settings_frame, textvariable=self.drizzle_var, values=["0", "1.0", "2.0"], state="readonly", width=8).grid(row=2, column=1, sticky=tk.W, pady=5)
        
        ttk.Label(settings_frame, text="Feather Width (px):").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.feather_var = tk.IntVar(value=150)
        ttk.Entry(settings_frame, textvariable=self.feather_var, width=10).grid(row=3, column=1, sticky=tk.W, pady=5)
        
        # Checkboxes
        self.mosaic_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(left_panel, text="Enable Mosaic Stacking (-overlap_norm)", variable=self.mosaic_var).pack(anchor=tk.W, pady=2)
        
        self.clean_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(left_panel, text="Clean Destination Directory First", variable=self.clean_var).pack(anchor=tk.W, pady=2)
        
        # Pre-Flight Status
        status_frame = ttk.LabelFrame(left_panel, text="Pre-flight Status", padding="10")
        status_frame.pack(fill=tk.X, pady=(10, 10))
        self.os_label = ttk.Label(status_frame, text="OS: Checking...")
        self.os_label.pack(anchor=tk.W)
        self.siril_label = ttk.Label(status_frame, text="Siril: Checking...")
        self.siril_label.pack(anchor=tk.W)
        self.graxpert_label = ttk.Label(status_frame, text="GraXpert: Checking...")
        self.graxpert_label.pack(anchor=tk.W)
        
        # Action Buttons
        btn_frame = ttk.Frame(left_panel)
        btn_frame.pack(fill=tk.X, pady=20)
        
        self.start_btn = ttk.Button(btn_frame, text="Start Stacking Run", command=self.start_pipeline)
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.stop_btn = ttk.Button(btn_frame, text="Stop Process", command=self.stop_pipeline, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        
        # --- Right Panel: PanedWindow for Preview and Logs ---
        right_pane = ttk.PanedWindow(main_frame, orient=tk.VERTICAL)
        right_pane.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Preview Frame
        preview_frame = ttk.LabelFrame(right_pane, text="Image Preview", padding="10")
        right_pane.add(preview_frame, weight=3)
        
        self.preview_label = ttk.Label(preview_frame, text="No preview available.")
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        
        btn_preview = ttk.Button(preview_frame, text="Refresh Preview", command=self.load_preview)
        btn_preview.pack(pady=5)
        
        # Logs Frame
        log_frame = ttk.LabelFrame(right_pane, text="Execution Terminal Logs", padding="10")
        right_pane.add(log_frame, weight=1)
        
        self.log_area = ScrolledText(log_frame, wrap=tk.WORD, bg="black", fg="lightgray", font=("Consolas", 10))
        self.log_area.pack(fill=tk.BOTH, expand=True)
        self.log_area.insert(tk.END, "Pipeline ready. Click 'Start Stacking Run' to initiate processing.\n")
        self.log_area.configure(state='disabled')
        
        # Keep a reference to the image to prevent garbage collection
        self.current_preview_img = None
        
        # Run Pre-flight Check
        self.run_preflight_check()
        
    def run_preflight_check(self):
        try:
            cmd = [sys.executable, os.path.join(self.pipeline_dir, "run_pipeline.py"), "--check"]
            creationflags = 0
            if sys.platform == 'win32':
                creationflags = subprocess.CREATE_NO_WINDOW
                
            res = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags)
            if res.returncode == 0:
                import json
                data = json.loads(res.stdout.strip())
                self.os_label.config(text=f"OS Detected: {data['os']}")
                
                siril = data['siril']
                if siril['ok']:
                    self.siril_label.config(text="✅ Siril: Found")
                else:
                    self.siril_label.config(text="❌ Siril: NOT FOUND")
                    self.start_btn.config(state=tk.DISABLED)
                    
                graxpert = data['graxpert']
                if graxpert['ok']:
                    self.graxpert_label.config(text="✅ GraXpert: Found")
                else:
                    self.graxpert_label.config(text="❌ GraXpert: NOT FOUND")
                    self.start_btn.config(state=tk.DISABLED)
            else:
                self.os_label.config(text="❌ Pre-flight check failed to run.")
        except Exception as e:
            self.os_label.config(text=f"❌ Error during check: {e}")
            
    def update_dest(self, *args):
        src = self.src_var.get().strip()
        dest = src
        if src.endswith("\\") or src.endswith("/"):
            sep = src[-1]
            dest = src[:-1] + "_sorted" + sep
        elif len(src) > 0:
            dest = src + "_sorted"
        self.dest_var.set(dest)
        
    def browse_src(self):
        folder = filedialog.askdirectory(title="Select Source Directory")
        if folder:
            folder = os.path.normpath(folder)
            self.src_var.set(folder)
            
    def append_log(self, text):
        self.log_area.configure(state='normal')
        self.log_area.insert(tk.END, text)
        self.log_area.see(tk.END)
        self.log_area.configure(state='disabled')

    def load_preview(self):
        dest = self.dest_var.get().strip()
        
        # Check files in order of preference
        possible_files = [
            "final_master_display_stretched.fit",
            "final_master_result_cropped.fits",
            "result.fit"
        ]
        
        fits_path = None
        for pf in possible_files:
            test_path = os.path.join(dest, pf)
            if os.path.exists(test_path):
                fits_path = test_path
                break
                
        if not fits_path:
            self.preview_label.config(image='', text="No display FITS found in destination directory.")
            return
            
        try:
            with fits.open(fits_path) as hdul:
                data = hdul[0].data
                if data is None and len(hdul) > 1:
                    data = hdul[1].data
            
            if data is None:
                raise ValueError("No image data found in FITS.")
                
            if data.ndim == 3:
                data = data[0]
                
            p_low, p_high = np.percentile(data, (2, 98))
            data = np.clip(data, p_low, p_high)
            data = (data - p_low) / (p_high - p_low + 1e-8)
            data = (data * 255).astype(np.uint8)
            
            data = np.flipud(data)
            
            pil_img = Image.fromarray(data)
            
            # Use Resampling.LANCZOS for newer PIL versions, fallback to LANCZOS
            resample_filter = getattr(Image.Resampling, 'LANCZOS', Image.LANCZOS) if hasattr(Image, 'Resampling') else Image.LANCZOS
            pil_img.thumbnail((1000, 800), resample_filter)
            
            self.current_preview_img = ImageTk.PhotoImage(pil_img)
            self.preview_label.config(image=self.current_preview_img, text="")
            self.append_log("\n[INFO] Preview loaded successfully.\n")
        except Exception as e:
            self.preview_label.config(image='', text=f"Error loading preview: {e}")
            self.append_log(f"\n[ERROR] Could not load preview: {e}\n")

    def start_pipeline(self):
        if self.pipeline_process is not None and self.pipeline_process.poll() is None:
            messagebox.showwarning("Warning", "Pipeline is already running.")
            return
            
        src = self.src_var.get().strip()
        dest = self.dest_var.get().strip()
        
        if not src:
            messagebox.showerror("Error", "Source Directory cannot be empty.")
            return
            
        # Build command
        cmd = [
            sys.executable,
            os.path.join(self.pipeline_dir, "run_pipeline.py"),
            "--src", src,
            "--dest", dest,
            "--threads", str(self.threads_var.get()),
            "--batch-size", str(self.batch_var.get()),
            "--feather-amount", str(self.feather_var.get())
        ]
        
        if self.mosaic_var.get():
            cmd.append("--mosaic")
            
        drizzle_val = self.drizzle_var.get()
        if drizzle_val and drizzle_val != "0":
            cmd.extend(["--drizzle", drizzle_val])
            
        if self.clean_var.get():
            cmd.append("--clean")
            
        self.append_log(f"\n[INFO] Starting pipeline...\n")
        self.append_log(f"Command: {' '.join(cmd)}\n\n")
        
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        def run_thread():
            try:
                creationflags = 0
                if sys.platform == 'win32':
                    creationflags = subprocess.CREATE_NO_WINDOW

                self.pipeline_process = subprocess.Popen(
                    cmd,
                    cwd=self.pipeline_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    creationflags=creationflags
                )
                
                for line in iter(self.pipeline_process.stdout.readline, ""):
                    self.root.after(0, self.append_log, line)
                    
                self.pipeline_process.wait()
                
                if self.pipeline_process.returncode == 0:
                    self.root.after(0, self.append_log, "\n[SUCCESS] Pipeline completed successfully.\n")
                    self.root.after(0, self.load_preview)
                else:
                    self.root.after(0, self.append_log, f"\n[ERROR] Pipeline exited with code {self.pipeline_process.returncode}.\n")
                    
            except Exception as e:
                self.root.after(0, self.append_log, f"\n[ERROR] Failed to start pipeline: {e}\n")
            finally:
                self.pipeline_process = None
                self.root.after(0, self.reset_buttons)
                
        threading.Thread(target=run_thread, daemon=True).start()
        
    def stop_pipeline(self):
        if self.pipeline_process is not None:
            self.append_log("\n[INFO] Sending terminate signal...\n")
            self.pipeline_process.terminate()
            
    def reset_buttons(self):
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    app = AstrophotographyGUI(root)
    root.mainloop()
