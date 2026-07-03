import platform
from pathlib import Path
import re
import subprocess
import O4_File_Names as FNAMES
import O4_UI_Utils as UI

overlay_types = ["Roads", "Trees", "Buildings"]

def build_overlay_dsfs(tile):
    if separate_overlays:
        for overlay_type in (generated_overlays if not clean_overlays else overlay_types):
            build_overlay_dsf(tile, overlay_type)
    else:
        build_combined_overlay_dsf(tile)

def build_overlay_dsf(tile, overlay_type):
    dsf_textPath = Path(tile.build_dir) / overlay_type / "Earth nav data" / FNAMES.round_latlon(tile.lat, tile.lon) / FNAMES.short_latlon(tile.lat, tile.lon) + ".txt" 

    if not dsf_textPath.exists():
        UI.lvprint(1, f"DSF text file for {overlay_type} not found at {dsf_textPath}. Skipping DSF generation for this overlay.")
        return

    dsf_outPath = Path(tile.build_dir) / overlay_type / "Earth nav data" / FNAMES.round_latlon(tile.lat, tile.lon) / FNAMES.short_latlon(tile.lat, tile.lon) + ".dsf"

    system = platform.system()
    if system == "Windows":
        exe_path = Path(FNAMES.Utils_dir) / "win" / "DSFTool.exe"
    elif system == "Darwin":  # macOS
        exe_path = Path(FNAMES.Utils_dir) / "mac" / "DSFTool"
    elif system == "Linux":
        exe_path = Path(FNAMES.Utils_dir) / "lin" / "DSFTool"
    else:
        UI.lvprint(1, f"Unsupported operating system: {system}")
        return

    cmd = [exe_path, "--text2dsf", dsf_textPath, dsf_outPath]
    subprocess.run(cmd, check=True)

    UI.lvprint(1, f"✓ {overlay_type} DSF generated at {dsf_outPath}")
    

def build_combined_overlay_dsf(tile):
    polygon_def_count = 0
    overlay_dict = {o: {"polygon_def_start_idx": 0, "header": "", "defs": "", "def_end_line": 0} for o in (generated_overlays if not clean_overlays else overlay_types)}

    for overlay_type in overlay_dict.keys():
        dsf_textPath = Path(tile.build_dir) / overlay_type / "Earth nav data" / FNAMES.round_latlon(tile.lat, tile.lon) / (FNAMES.short_latlon(tile.lat, tile.lon) + ".txt") 
        if dsf_textPath.exists():
            if overlay_type != "Roads":
                overlay_dict[overlay_type]["polygon_def_start_idx"] = polygon_def_count
                UI.lvprint(1, f"Overlay {overlay_type} polygon defs will start at index {polygon_def_count} in combined DSF")
            else:
                overlay_dict[overlay_type]["polygon_def_start_idx"] = None

            with open(dsf_textPath, 'r') as f:
                def_seen = False
                for lineno, line in enumerate(f, 1):
                    if line.startswith("POLYGON_DEF"):
                        def_seen = True
                        polygon_def_count += 1
                        overlay_dict[overlay_type]["defs"] += line
                    elif line.startswith("NETWORK_DEF"):
                        def_seen = True
                        overlay_dict[overlay_type]["defs"] += line
                    elif def_seen:
                        overlay_dict[overlay_type]["def_end_line"] = lineno
                        break
                    else:
                        overlay_dict[overlay_type]["header"] += line
        else:
            UI.lvprint(1, f"DSF text file for {overlay_type} not found at {dsf_textPath}. Skipping this overlay in combined DSF generation.")
            overlay_dict.pop(overlay_type, None)

    combined_header = "".join(overlay_dict[o]["header"] for o in overlay_dict)
    combined_defs = "".join(overlay_dict[o]["defs"] for o in overlay_dict)
    combined_dsf_textPath = Path(tile.build_dir) / "Overlays" / "Earth nav data" / FNAMES.round_latlon(tile.lat, tile.lon) / (FNAMES.short_latlon(tile.lat, tile.lon) + ".txt")
    combined_dsf_outPath = Path(tile.build_dir) / "Overlays" / "Earth nav data" / FNAMES.round_latlon(tile.lat, tile.lon) / (FNAMES.short_latlon(tile.lat, tile.lon) + ".dsf")
    combined_dsf_textPath.parent.mkdir(parents=True, exist_ok=True)

    with open(combined_dsf_textPath, 'w', encoding='utf-8') as dst:
        dst.write(combined_header)
        dst.write(combined_defs)

        for overlay_type in overlay_dict.keys():
            src_path = Path(tile.build_dir) / overlay_type / "Earth nav data" / FNAMES.round_latlon(tile.lat, tile.lon) / (FNAMES.short_latlon(tile.lat, tile.lon) + ".txt")
            UI.lvprint(1, f"Processing {overlay_type} for combined DSF from {src_path}")
            with open(src_path, 'r', encoding='utf-8') as src:
                for lineno, line in enumerate(src, 1):
                    if lineno < overlay_dict[overlay_type]["def_end_line"]:
                        UI.lvprint(1, f"Skipping line {lineno} of {overlay_type} (header/defs already included)")
                        continue
                    if line.startswith("BEGIN_POLYGON"):
                        def add(match): return str(int(match.group(0)) + overlay_dict[overlay_type]["polygon_def_start_idx"])
                        dst.write(re.sub(r"\d+", add, line, count=1))
                    else:
                        dst.write(line)
                    
                    

    system = platform.system()
    if system == "Windows":
        exe_path = Path(FNAMES.Utils_dir) / "win" / "DSFTool.exe"
    elif system == "Darwin":  # macOS
        exe_path = Path(FNAMES.Utils_dir) / "mac" / "DSFTool"
    elif system == "Linux":
        exe_path = Path(FNAMES.Utils_dir) / "lin" / "DSFTool"
    else:
        UI.lvprint(1, f"Unsupported operating system: {system}")
        return

    cmd = [exe_path, "--text2dsf", combined_dsf_textPath, combined_dsf_outPath]
    subprocess.run(cmd, check=True)

    UI.lvprint(1, f"✓ Overlay DSF generated at {combined_dsf_outPath}")