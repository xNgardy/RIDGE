#!/usr/bin/env python3
"""Small Tkinter GUI for launching the automatic non-XPlane mask pipeline."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk


THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parents[2]
DATA_PIPELINE = PROJECT_ROOT / "Data_Pipeline"


class PipelineGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("RIDGE Automatic Mask Pipeline")
        self.geometry("980x720")
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.process: subprocess.Popen | None = None

        self.vars = {
            "python": tk.StringVar(value=sys.executable),
            "rgb_tifs": tk.StringVar(value=str(DATA_PIPELINE / "outputs" / "RGB_tifs")),
            "unity_output": tk.StringVar(value=str(DATA_PIPELINE / "outputs" / "unity_output")),
            "ndvi_file": tk.StringVar(value=""),
            "building_images": tk.StringVar(value=str(DATA_PIPELINE / "outputs" / "unity_output" / "tiles_rgb")),
            "unity_package_dir": tk.StringVar(value=str(DATA_PIPELINE / "outputs" / "unity_ready" / "Terrain_Tiles")),
            "building_detector": tk.StringVar(value="roboflow"),
            "ramp_building_model": tk.StringVar(
                value=str(DATA_PIPELINE / "src" / "Building_Detection_Module" / "ramp_xunet.onnx")
            ),
            "tree_threshold": tk.StringVar(value="0.4"),
            "tree_density": tk.StringVar(value="0.05"),
            "building_confidence": tk.StringVar(value="40"),
            "roboflow_api_key": tk.StringVar(value=""),
            "skip_roads": tk.BooleanVar(value=False),
            "skip_road_json": tk.BooleanVar(value=False),
            "skip_ndvi_tiling": tk.BooleanVar(value=False),
            "skip_trees": tk.BooleanVar(value=False),
            "skip_buildings": tk.BooleanVar(value=False),
            "low_is_tree": tk.BooleanVar(value=True),
            "invert_tree_mask": tk.BooleanVar(value=False),
        }

        self._build_ui()
        self.after(100, self._poll_log_queue)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        paths = ttk.LabelFrame(root, text="Inputs")
        paths.pack(fill="x")

        self._path_row(paths, "Python", "python", file=True)
        self._path_row(paths, "RGB GeoTIFF folder", "rgb_tifs", directory=True)
        self._path_row(paths, "Unity output folder", "unity_output", directory=True)
        self._path_row(paths, "NDVI TIFF", "ndvi_file", file=True)
        self._path_row(paths, "Building image tiles", "building_images", directory=True)
        self._path_row(paths, "RAMP building model", "ramp_building_model", file=True)
        self._path_row(paths, "Unity package output", "unity_package_dir", directory=True)

        options = ttk.LabelFrame(root, text="Options")
        options.pack(fill="x", pady=(10, 0))

        ttk.Label(options, text="Building detector").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            options,
            textvariable=self.vars["building_detector"],
            values=("roboflow", "ramp"),
            state="readonly",
            width=18,
        ).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        self._entry_row(options, "Building confidence", "building_confidence", 0, 2)
        self._entry_row(options, "Tree threshold", "tree_threshold", 1, 0)
        self._entry_row(options, "Tree density", "tree_density", 1, 2)
        self._entry_row(options, "Roboflow API key", "roboflow_api_key", 2, 0, show="*")

        checks = ttk.Frame(options)
        checks.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 4))
        for key, label in [
            ("low_is_tree", "Low NDVI means tree"),
            ("invert_tree_mask", "Invert tree mask"),
            ("skip_roads", "Skip roads"),
            ("skip_road_json", "Skip road JSON"),
            ("skip_ndvi_tiling", "Skip NDVI tiling"),
            ("skip_trees", "Skip trees"),
            ("skip_buildings", "Skip buildings"),
        ]:
            ttk.Checkbutton(checks, text=label, variable=self.vars[key]).pack(side="left", padx=(0, 16))

        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=10)
        self.run_button = ttk.Button(actions, text="Run Pipeline", command=self._run_pipeline)
        self.run_button.pack(side="left")
        ttk.Button(actions, text="Stop", command=self._stop_pipeline).pack(side="left", padx=8)

        log_frame = ttk.LabelFrame(root, text="Log")
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, wrap="word", height=24)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)

    def _path_row(self, parent: ttk.Frame, label: str, key: str, *, file: bool = False, directory: bool = False) -> None:
        row = len(parent.grid_slaves()) // 3
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(parent, textvariable=self.vars[key]).grid(row=row, column=1, sticky="ew", padx=6, pady=4)
        parent.columnconfigure(1, weight=1)
        command = lambda: self._browse(key, file=file, directory=directory)
        ttk.Button(parent, text="Browse", command=command).grid(row=row, column=2, padx=6, pady=4)

    def _entry_row(self, parent: ttk.Frame, label: str, key: str, row: int, col: int, *, show: str | None = None) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=6, pady=4)
        ttk.Entry(parent, textvariable=self.vars[key], show=show).grid(row=row, column=col + 1, sticky="ew", padx=6, pady=4)
        parent.columnconfigure(col + 1, weight=1)

    def _browse(self, key: str, *, file: bool, directory: bool) -> None:
        if directory:
            selected = filedialog.askdirectory()
        elif file:
            selected = filedialog.askopenfilename()
        else:
            selected = ""
        if selected:
            self.vars[key].set(selected)

    def _build_command(self) -> list[str]:
        runner = THIS_DIR / "pipeline_runner.py"
        command = [
            self.vars["python"].get(),
            str(runner),
            "--python",
            self.vars["python"].get(),
            "--rgb-tifs",
            self.vars["rgb_tifs"].get(),
            "--unity-output",
            self.vars["unity_output"].get(),
            "--building-images",
            self.vars["building_images"].get(),
            "--unity-package-dir",
            self.vars["unity_package_dir"].get(),
            "--building-detector",
            self.vars["building_detector"].get(),
            "--ramp-building-model",
            self.vars["ramp_building_model"].get(),
            "--tree-threshold",
            self.vars["tree_threshold"].get(),
            "--tree-density",
            self.vars["tree_density"].get(),
            "--building-confidence",
            self.vars["building_confidence"].get(),
        ]

        if self.vars["ndvi_file"].get():
            command.extend(["--ndvi-file", self.vars["ndvi_file"].get()])
        if self.vars["roboflow_api_key"].get():
            command.extend(["--roboflow-api-key", self.vars["roboflow_api_key"].get()])

        for key, flag in [
            ("skip_roads", "--skip-roads"),
            ("skip_road_json", "--skip-road-json"),
            ("skip_ndvi_tiling", "--skip-ndvi-tiling"),
            ("skip_trees", "--skip-trees"),
            ("skip_buildings", "--skip-buildings"),
            ("low_is_tree", "--low-is-tree"),
            ("invert_tree_mask", "--invert-tree-mask"),
        ]:
            if self.vars[key].get():
                command.append(flag)

        return command

    def _run_pipeline(self) -> None:
        if self.process is not None:
            self._append_log("A pipeline run is already active.\n")
            return

        command = self._build_command()
        self._append_log("\nStarting pipeline...\n> " + " ".join(command) + "\n\n")
        self.run_button.configure(state="disabled")
        thread = threading.Thread(target=self._worker, args=(command,), daemon=True)
        thread.start()

    def _worker(self, command: list[str]) -> None:
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
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

    def _stop_pipeline(self) -> None:
        if self.process is not None:
            self.process.terminate()
            self._append_log("\nStop requested.\n")

    def _poll_log_queue(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if line == "__RUN_DONE__":
                self.run_button.configure(state="normal")
            else:
                self._append_log(line)
        self.after(100, self._poll_log_queue)

    def _append_log(self, text: str) -> None:
        self.log.insert("end", text)
        self.log.see("end")


def main() -> None:
    app = PipelineGui()
    app.mainloop()


if __name__ == "__main__":
    main()
