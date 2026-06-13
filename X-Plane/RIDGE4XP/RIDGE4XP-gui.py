#!/usr/bin/env python3
import os
import sys
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

# Fix up the python path to include the 'src' dir to import O4_Config_Utils
THIS_DIR = Path(__file__).resolve().parent
SRC_DIR = THIS_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import O4_Config_Utils as CFG

BASIC_VARS = [
    "local_data_root", "mesh_zl", "curvature_tol", "mask_zl",
    "masking_mode", "masks_width", "ratio_water", "use_masks_for_inland",
    "default_zl", "fill_nodata", "normal_map_strength", "custom_overlay_src",
    "cleaning_level", "verbosity", "min_hole_area_px", "separate_overlays",
    "generated_overlays"
]

class Ridge4XPGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RIDGE4XP Configuration GUI")
        self.geometry("980x720")
        
        self.log_queue = queue.Queue()
        self.process = None

        self.lat_var = tk.StringVar()
        self.lon_var = tk.StringVar()
        self.advanced_var = tk.BooleanVar(value=False)
        self.selected_var_to_add = tk.StringVar()
        
        # Dictionary to track active variables: {var_name: {"tk_var": tk_var, "frame": tk_frame, "type": type}}
        self.active_vars = {}
        
        self._build_ui()
        self._update_available_vars()
        self.after(100, self._poll_log_queue)

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding=12)
        main_frame.pack(fill="both", expand=True)
        
        # Coordinates
        coord_frame = ttk.LabelFrame(main_frame, text="Target Tile", padding=10)
        coord_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(coord_frame, text="Latitude (e.g. 42):").pack(side="left", padx=5)
        ttk.Entry(coord_frame, textvariable=self.lat_var, width=10).pack(side="left", padx=5)
        
        ttk.Label(coord_frame, text="Longitude (e.g. -71):").pack(side="left", padx=5)
        ttk.Entry(coord_frame, textvariable=self.lon_var, width=10).pack(side="left", padx=5)
        
        # Variable Controls
        ctrl_frame = ttk.Frame(main_frame)
        ctrl_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Checkbutton(ctrl_frame, text="Advanced Configuration", variable=self.advanced_var, command=self._update_available_vars).pack(side="left", padx=(0, 15))
        
        ttk.Label(ctrl_frame, text="Add Variable:").pack(side="left", padx=5)
        self.var_combobox = ttk.Combobox(ctrl_frame, textvariable=self.selected_var_to_add, state="readonly", width=40)
        self.var_combobox.pack(side="left", padx=5)
        
        ttk.Button(ctrl_frame, text="Add", command=self._add_variable).pack(side="left", padx=5)
        
        # Variables List Area (Scrollable)
        list_lf = ttk.LabelFrame(main_frame, text="Configuration Variables", padding=5)
        list_lf.pack(fill="both", expand=True, pady=(0, 10))
        
        self.canvas = tk.Canvas(list_lf, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_lf, orient="vertical", command=self.canvas.yview)
        self.vars_frame = ttk.Frame(self.canvas)
        
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        
        self.canvas_window = self.canvas.create_window((0, 0), window=self.vars_frame, anchor="nw")
        self.vars_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        
        # Action Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=(0, 10))
        
        self.run_btn = ttk.Button(btn_frame, text="Generate & Run", command=self._generate_and_run)
        self.run_btn.pack(side="left", padx=(0, 10))
        
        ttk.Button(btn_frame, text="Stop", command=self._stop_pipeline).pack(side="left")
        
        # Log output
        log_lf = ttk.LabelFrame(main_frame, text="Log Output")
        log_lf.pack(fill="both", expand=True)
        
        self.log_text = tk.Text(log_lf, wrap="word", height=15)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_lf, orient="vertical", command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _update_available_vars(self):
        all_cfg = CFG.cfg_vars.keys()
        available = []
        
        for k in all_cfg:
            if k in self.active_vars:
                continue
            if not self.advanced_var.get() and k not in BASIC_VARS:
                continue
            available.append(k)
            
        available.sort()
        self.var_combobox['values'] = available
        if available:
            if self.selected_var_to_add.get() not in available:
                self.var_combobox.current(0)
        else:
            self.selected_var_to_add.set('')

    def _add_variable(self):
        var_name = self.selected_var_to_add.get()
        if not var_name or var_name in self.active_vars:
            return
        
        var_info = CFG.cfg_vars[var_name]
        vtype = var_info.get("type", str)
        vdef = var_info.get("default", "")
        vhint = var_info.get("hint", "")
        
        # Create row frame
        row_frame = ttk.Frame(self.vars_frame, borderwidth=1, relief="solid", padding=5)
        row_frame.pack(fill="x", pady=2, padx=2)
        
        top_part = ttk.Frame(row_frame)
        top_part.pack(fill="x")
        
        ttk.Label(top_part, text=var_name, width=25, font=("TkDefaultFont", 9, "bold")).pack(side="left")
        
        # Value input widget
        tk_var = tk.StringVar(value=str(vdef))
        if vtype == bool:
            tk_var = tk.BooleanVar(value=vdef)
            cb = ttk.Checkbutton(top_part, text="Enabled", variable=tk_var)
            cb.pack(side="left", padx=10, fill="x", expand=True)
        elif "values" in var_info:
            vals = [str(x) for x in var_info["values"]]
            cb = ttk.Combobox(top_part, textvariable=tk_var, values=vals, state="readonly")
            cb.pack(side="left", padx=10, fill="x", expand=True)
        else:
            ent = ttk.Entry(top_part, textvariable=tk_var)
            ent.pack(side="left", padx=10, fill="x", expand=True)
            
        ttk.Button(top_part, text="Remove", command=lambda v=var_name: self._remove_variable(v)).pack(side="right")
        
        # Hint text
        if vhint:
            hint_lbl = ttk.Label(row_frame, text=vhint, wraplength=900, foreground="gray")
            hint_lbl.pack(fill="x", pady=(2, 0))
            
        self.active_vars[var_name] = {"tk_var": tk_var, "frame": row_frame, "type": vtype}
        
        # Refresh combo
        self._update_available_vars()

    def _remove_variable(self, var_name):
        if var_name in self.active_vars:
            self.active_vars[var_name]["frame"].destroy()
            del self.active_vars[var_name]
            self._update_available_vars()

    def _generate_and_run(self):
        lat = self.lat_var.get().strip()
        lon = self.lon_var.get().strip()
        
        if not lat or not lon:
            messagebox.showerror("Error", "Latitude and Longitude are required.")
            return
        
        # Generate config
        cfg_path = THIS_DIR / "RIDGE4XP.cfg"
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                # Write only selected active vars
                for var_name, data in self.active_vars.items():
                    tk_var = data["tk_var"]
                    vtype = data["type"]
                    val = tk_var.get()
                    
                    if vtype == bool:
                        f.write(f"{var_name}={val}\n")
                    elif vtype == list:
                        val_str = val.strip()
                        # Light validation to ensure it looks like a python list
                        if not val_str.startswith("["):
                            val_str = f"[{val_str}]"
                        f.write(f"{var_name}={val_str}\n")
                    else:
                        f.write(f"{var_name}={val}\n")
            self._append_log(f"Config saved to {cfg_path}\n")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save config: {e}")
            return

        if self.process is not None:
            self._append_log("A pipeline run is already active.\n")
            return

        script_path = str(THIS_DIR / "RIDGE4XP.py")
        cmd = [sys.executable, script_path, lat, lon]
        self._append_log(f"\nStarting RIDGE4XP...\n> {' '.join(cmd)}\n\n")
        
        self.run_btn.configure(state="disabled")
        thread = threading.Thread(target=self._worker, args=(cmd,), daemon=True)
        thread.start()

    def _worker(self, command):
        try:
            # 1. Force the subprocess to use UTF-8 by overriding its environment variable
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            self.process = subprocess.Popen(
                command,
                cwd=str(THIS_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",    # 2. Tell the GUI to read the pipe as UTF-8
                errors="replace",    # 3. Safely replace any stubborn characters
                bufsize=1,
                env=env              # 4. Pass the modified environment variables
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.log_queue.put(line)
            return_code = self.process.wait()
            self.log_queue.put(f"\nPipeline exited with code {return_code}.\n")
        except Exception as exc:
            self.log_queue.put(f"\nPipeline failed to start: {exc}\n")
        finally:
            self.process = None
            self.log_queue.put("__RUN_DONE__")

    def _stop_pipeline(self):
        if self.process is not None:
            self.process.terminate()
            self._append_log("\nStop requested.\n")

    def _poll_log_queue(self):
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if line == "__RUN_DONE__":
                self.run_btn.configure(state="normal")
            else:
                self._append_log(line)
        self.after(100, self._poll_log_queue)

    def _append_log(self, text):
        self.log_text.insert("end", text)
        self.log_text.see("end")

if __name__ == "__main__":
    app = Ridge4XPGui()
    app.mainloop()