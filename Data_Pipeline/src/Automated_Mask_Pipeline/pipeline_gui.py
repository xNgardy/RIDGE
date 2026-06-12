#!/usr/bin/env python3

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
DEFAULT_RAMP_BUILDING_MODEL = (
    DATA_PIPELINE
    / "src"
    / "Building_Detection_Module"
    / "models"
    / "building-footprint-extract"
    / "3"
    / "weights.onnx"
)


class PipelineGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("RIDGE Fully Automatic Unity Pipeline")
        self.geometry("1080x800")
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.process: subprocess.Popen | None = None
        self.skip_widgets: list[tk.Widget] = []

        self.vars = {
            "python": tk.StringVar(value=sys.executable),
            "input_mode": tk.StringVar(value="raw"),
            "raw_rgb_file": tk.StringVar(value=""),
            "dem_file": tk.StringVar(value=""),
            "work_dir": tk.StringVar(value=str(DATA_PIPELINE / "outputs" / "automatic_run")),
            "tile_size": tk.StringVar(value="512"),
            "rgb_tifs": tk.StringVar(value=str(DATA_PIPELINE / "outputs" / "RGB_tifs")),
            "unity_output": tk.StringVar(value=str(DATA_PIPELINE / "outputs" / "unity_output")),
            "ndvi_file": tk.StringVar(value=""),
            "unity_package_dir": tk.StringVar(value=str(DATA_PIPELINE / "outputs" / "unity_ready" / "Terrain_Tiles")),
            "building_detector": tk.StringVar(value="ramp"),
            "ramp_building_model": tk.StringVar(value=str(DEFAULT_RAMP_BUILDING_MODEL)),
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
        self._update_input_mode()
        self.after(100, self._poll_log_queue)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        mode_frame = ttk.LabelFrame(root, text="Input Mode")
        mode_frame.pack(fill="x")
        ttk.Radiobutton(
            mode_frame,
            text="Raw GeoTIFFs: build all tiles and metadata automatically",
            variable=self.vars["input_mode"],
            value="raw",
            command=self._update_input_mode,
        ).pack(anchor="w", padx=8, pady=(6, 2))
        ttk.Radiobutton(
            mode_frame,
            text="Prepared tiles: use existing RGB_tifs and unity_output",
            variable=self.vars["input_mode"],
            value="prepared",
            command=self._update_input_mode,
        ).pack(anchor="w", padx=8, pady=(2, 6))

        self.raw_paths = ttk.LabelFrame(root, text="Raw GeoTIFF Inputs")
        self._path_row(self.raw_paths, "Raw RGB GeoTIFF", "raw_rgb_file", file=True)
        self._path_row(self.raw_paths, "Raw DEM GeoTIFF", "dem_file", file=True)
        self._path_row(self.raw_paths, "Raw NDVI GeoTIFF", "ndvi_file", file=True)
        self._path_row(self.raw_paths, "Intermediate workspace", "work_dir", directory=True)
        self._entry_row(self.raw_paths, "Tile size (pixels)", "tile_size")

        self.prepared_paths = ttk.LabelFrame(root, text="Existing Prepared Inputs")
        self._path_row(self.prepared_paths, "RGB GeoTIFF tiles folder", "rgb_tifs", directory=True)
        self._path_row(self.prepared_paths, "Existing Unity Tile Data", "unity_output", directory=True)

        self.outputs_frame = ttk.LabelFrame(root, text="Unity Output")
        self.outputs_frame.pack(fill="x", pady=(10, 0))
        self._path_row(
            self.outputs_frame,
            "Final Terrain_Tiles folder",
            "unity_package_dir",
            directory=True,
        )

        options = ttk.LabelFrame(root, text="Options")
        options.pack(fill="x", pady=(10, 0))

        self._path_row(options, "Python", "python", file=True)
        self._path_row(options, "RAMP building model", "ramp_building_model", file=True)
        ttk.Label(options, text="Building detector").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            options,
            textvariable=self.vars["building_detector"],
            values=("roboflow", "ramp"),
            state="readonly",
            width=18,
        ).grid(row=2, column=1, sticky="ew", padx=6, pady=4)
        self._entry_row(options, "Building confidence", "building_confidence", row=2, col=2)
        self._entry_row(options, "Tree threshold", "tree_threshold", row=3, col=0)
        self._entry_row(options, "Tree density", "tree_density", row=3, col=2)
        self._entry_row(options, "Roboflow API key", "roboflow_api_key", row=4, col=0, show="*")

        checks = ttk.Frame(options)
        checks.grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 4))
        for key, label in [
            ("low_is_tree", "Low NDVI means tree"),
            ("invert_tree_mask", "Invert tree mask"),
            ("skip_roads", "Skip roads"),
            ("skip_road_json", "Skip road JSON"),
            ("skip_ndvi_tiling", "Skip NDVI tiling"),
            ("skip_trees", "Skip trees"),
            ("skip_buildings", "Skip buildings"),
        ]:
            checkbox = ttk.Checkbutton(checks, text=label, variable=self.vars[key])
            checkbox.pack(side="left", padx=(0, 16))
            if key.startswith("skip_"):
                self.skip_widgets.append(checkbox)

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

    def _path_row(
        self,
        parent: ttk.Frame,
        label: str,
        key: str,
        *,
        file: bool = False,
        directory: bool = False,
    ) -> list[tk.Widget]:
        row = len(parent.grid_slaves()) // 3
        label_widget = ttk.Label(parent, text=label)
        label_widget.grid(row=row, column=0, sticky="w", padx=6, pady=4)
        entry = ttk.Entry(parent, textvariable=self.vars[key])
        entry.grid(row=row, column=1, sticky="ew", padx=6, pady=4)
        parent.columnconfigure(1, weight=1)
        command = lambda: self._browse(key, file=file, directory=directory)
        button = ttk.Button(parent, text="Browse", command=command)
        button.grid(row=row, column=2, padx=6, pady=4)
        return [label_widget, entry, button]

    def _entry_row(
        self,
        parent: ttk.Frame,
        label: str,
        key: str,
        row: int | None = None,
        col: int = 0,
        *,
        show: str | None = None,
    ) -> list[tk.Widget]:
        if row is None:
            row = len(parent.grid_slaves()) // 3
        label_widget = ttk.Label(parent, text=label)
        label_widget.grid(row=row, column=col, sticky="w", padx=6, pady=4)
        entry = ttk.Entry(parent, textvariable=self.vars[key], show=show)
        entry.grid(row=row, column=col + 1, sticky="ew", padx=6, pady=4)
        parent.columnconfigure(col + 1, weight=1)
        return [label_widget, entry]

    def _update_input_mode(self) -> None:
        raw_mode = self.vars["input_mode"].get() == "raw"
        self.raw_paths.pack_forget()
        self.prepared_paths.pack_forget()
        visible_panel = self.raw_paths if raw_mode else self.prepared_paths
        visible_panel.pack(
            fill="x",
            pady=(10, 0),
            before=self.outputs_frame,
        )
        for widget in self.skip_widgets:
            widget.configure(state="disabled" if raw_mode else "normal")
        for key in ("skip_roads", "skip_road_json", "skip_ndvi_tiling", "skip_trees", "skip_buildings"):
            if raw_mode:
                self.vars[key].set(False)

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
            "--input-mode",
            self.vars["input_mode"].get(),
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

        if self.vars["input_mode"].get() == "raw":
            command.extend([
                "--raw-rgb-file",
                self.vars["raw_rgb_file"].get(),
                "--dem-file",
                self.vars["dem_file"].get(),
                "--work-dir",
                self.vars["work_dir"].get(),
                "--tile-size",
                self.vars["tile_size"].get(),
            ])
        else:
            command.extend([
                "--rgb-tifs",
                self.vars["rgb_tifs"].get(),
                "--unity-output",
                self.vars["unity_output"].get(),
                "--skip-ndvi-tiling",
            ])

        if self.vars["input_mode"].get() == "raw" and self.vars["ndvi_file"].get():
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
