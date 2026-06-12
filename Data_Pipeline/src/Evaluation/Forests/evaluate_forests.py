#!/usr/bin/env python3
"""
Forest / tree-mask segmentation evaluation.

This mirrors the building evaluation workflow, but labels the report for
forest-mask / tree-canopy polygons. Inputs can be shapefiles, or a directory of
binary mask PNGs with matching reference GeoTIFF tiles.

Examples:
    python Data_Pipeline/src/Tree_Detection_Module/evaluate_forests.py \
        --gt Data_Pipeline/src/Tree_Detection_Module/forests/forest.shp \
        --pred Data_Pipeline/src/Tree_Detection_Module/forests/forests.shp \
        --output Data_Pipeline/src/Tree_Detection_Module/forest_evaluation.csv

    python Data_Pipeline/src/Tree_Detection_Module/evaluate_forests.py \
        --gt Data_Pipeline/src/Tree_Detection_Module/forests/forest.shp \
        --pred-mask-dir Data_Pipeline/outputs/unity_output/tiles_trees \
        --pred-ref-dir Data_Pipeline/outputs/unity_output/tiles_height_tif \
        --output Data_Pipeline/src/Tree_Detection_Module/forest_evaluation.csv
"""

from __future__ import annotations

import argparse
import datetime
import io
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape
from shapely.ops import unary_union

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evaluate_buildings import (  # noqa: E402
    boundary_iou,
    clean_geodataframe,
    compute_ap,
    fmt,
    pixel_level_metrics,
    stats_summary,
)

warnings.filterwarnings("ignore")


class Tee:
    def __init__(self):
        self._terminal = sys.stdout
        self._buf = io.StringIO()

    def write(self, msg):
        self._terminal.write(msg)
        self._buf.write(msg)

    def flush(self):
        self._terminal.flush()

    def getvalue(self):
        return self._buf.getvalue()


def vectorize_mask_dir(mask_dir: Path, ref_dir: Path, min_area_px: float) -> gpd.GeoDataFrame:
    rows = []
    crs = None

    mask_paths = sorted(mask_dir.glob("*_mask.png"))
    if not mask_paths:
        mask_paths = sorted(mask_dir.glob("*.png"))
    if not mask_paths:
        raise SystemExit(f"[ERROR] No PNG masks found in {mask_dir}")

    for mask_path in mask_paths:
        tile_name = mask_path.name.replace("_mask.png", "").replace(".png", "")
        ref_path = ref_dir / f"{tile_name}.tif"
        if not ref_path.exists():
            ref_path = ref_dir / f"{tile_name}.tiff"
        if not ref_path.exists():
            print(f"  [WARN] Skipping {mask_path.name}: missing reference GeoTIFF")
            continue

        with rasterio.open(mask_path) as mask_src, rasterio.open(ref_path) as ref_src:
            mask = mask_src.read(1) > 0
            crs = ref_src.crs
            transform = ref_src.transform
            for geom, value in shapes(mask.astype("uint8"), mask=mask, transform=transform):
                if value != 1:
                    continue
                poly = shape(geom)
                if poly.is_empty or poly.area < min_area_px * abs(transform.a * transform.e):
                    continue
                rows.append({"tile": tile_name, "geometry": poly})

    if not rows:
        raise SystemExit("[ERROR] No forest polygons were vectorized from the mask directory.")

    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)


def boundary_band(geom, width: float):
    outer = geom.buffer(width / 2)
    inner = geom.buffer(-width / 2)
    band = outer.difference(inner)
    return band if not band.is_empty else outer


def forest_boundary_f1(gt_geom, pred_geom, width: float):
    gt_band = boundary_band(gt_geom, width)
    pred_band = boundary_band(pred_geom, width)
    inter = gt_band.intersection(pred_band).area
    precision = inter / pred_band.area if pred_band.area > 0 else 0.0
    recall = inter / gt_band.area if gt_band.area > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def match_forest_objects(gt_gdf, pred_gdf, iou_threshold, boundary_width):
    matched_gt = set()
    matched_pred = set()
    matches = []
    pred_sindex = pred_gdf.sindex

    for gt_idx, gt_row in gt_gdf.iterrows():
        gt_geom = gt_row.geometry
        candidates = list(pred_sindex.intersection(gt_geom.bounds))
        best_iou = 0.0
        best_pred_idx = None

        for pred_idx in candidates:
            pred_geom = pred_gdf.iloc[pred_idx].geometry
            inter_area = gt_geom.intersection(pred_geom).area
            if inter_area == 0:
                continue
            union_area = gt_geom.union(pred_geom).area
            iou = inter_area / union_area if union_area > 0 else 0.0
            if iou > best_iou:
                best_iou = iou
                best_pred_idx = pred_idx

        if best_pred_idx is None or best_iou < iou_threshold or best_pred_idx in matched_pred:
            continue

        pred_geom = pred_gdf.iloc[best_pred_idx].geometry
        b_precision, b_recall, b_f1 = forest_boundary_f1(gt_geom, pred_geom, boundary_width)
        matches.append(
            {
                "gt_idx": gt_idx,
                "pred_idx": best_pred_idx,
                "IoU": best_iou,
                "Boundary_IoU": boundary_iou(gt_geom, pred_geom, boundary_width),
                "Boundary_Precision": b_precision,
                "Boundary_Recall": b_recall,
                "Boundary_F1": b_f1,
                "Hausdorff_m": gt_geom.hausdorff_distance(pred_geom),
                "Centroid_dist_m": gt_geom.centroid.distance(pred_geom.centroid),
                "GT_area_m2": gt_geom.area,
                "Pred_area_m2": pred_geom.area,
            }
        )
        matched_gt.add(gt_idx)
        matched_pred.add(best_pred_idx)

    tp_indices = [m["gt_idx"] for m in matches]
    fp_indices = [idx for idx in range(len(pred_gdf)) if idx not in matched_pred]
    fn_indices = [idx for idx in range(len(gt_gdf)) if idx not in matched_gt]
    return matches, tp_indices, fp_indices, fn_indices


def object_level_metrics(matches, n_gt, n_pred):
    n_tp = len(matches)
    n_fp = n_pred - n_tp
    n_fn = n_gt - n_tp
    return {
        "N_GT": n_gt,
        "N_Pred": n_pred,
        "TP": n_tp,
        "FP": n_fp,
        "FN": n_fn,
        "Completeness": n_tp / n_gt if n_gt > 0 else 0.0,
        "Correctness": n_tp / n_pred if n_pred > 0 else 0.0,
        "Quality_Rate": n_tp / (n_tp + n_fp + n_fn) if (n_tp + n_fp + n_fn) > 0 else 0.0,
    }


def load_input(path: str | None, mask_dir: str | None, ref_dir: str | None, min_area_px: float):
    if path:
        return gpd.read_file(path), Path(path)
    if mask_dir:
        if not ref_dir:
            raise SystemExit("[ERROR] Mask-directory input requires the matching --*-ref-dir.")
        return vectorize_mask_dir(Path(mask_dir), Path(ref_dir), min_area_px), Path(mask_dir)
    raise SystemExit("[ERROR] Provide either a shapefile path or a mask directory.")


def clip_to_extent(gdf: gpd.GeoDataFrame, extent_path: str, epsg: int, name: str) -> gpd.GeoDataFrame:
    extent = gpd.read_file(extent_path)
    if extent.empty:
        raise SystemExit(f"[ERROR] Clip extent is empty: {extent_path}")
    if extent.crs is None:
        raise SystemExit(f"[ERROR] Clip extent has no CRS: {extent_path}")

    extent = extent.to_crs(epsg=epsg)
    clip_geom = extent.geometry.union_all()
    clipped = gdf.copy()
    clipped["geometry"] = clipped.geometry.intersection(clip_geom)
    clipped = clipped[~clipped.geometry.is_empty & ~clipped.geometry.isna()].copy()
    print(f"  [{name}] clipped to extent: {len(gdf)} rows -> {len(clipped)} rows")
    return clipped


def save_readable_csv(output_path, pix, obj, ap50, ap5095, per_forest_stats, matches, study_area):
    rows = []

    def r(section, metric, value, notes=""):
        rows.append({"Section": section, "Metric": metric, "Value": value, "Notes": notes})

    s = "A - Pixel-level"
    r(s, "Study Area (m2)", round(study_area, 2), "Bounding-box union of GT + Pred")
    r(s, "IoU (Jaccard)", round(pix["IoU_Jaccard"], 6), "Intersection over Union")
    r(s, "Dice / F1", round(pix["F1_Dice"], 6), "2*TP / (2*TP+FP+FN)")
    r(s, "Precision", round(pix["Precision"], 6), "TP / (TP+FP)")
    r(s, "Recall", round(pix["Recall"], 6), "TP / (TP+FN)")
    r(s, "Pixel Accuracy", round(pix["Pixel_Accuracy"], 6), "(TP+TN) / total area")
    r(s, "mIoU", round(pix["mIoU"], 6), "Mean of forest-IoU and background-IoU")
    r(s, "TP area (m2)", round(pix["TP_area_m2"], 2))
    r(s, "FP area (m2)", round(pix["FP_area_m2"], 2))
    r(s, "FN area (m2)", round(pix["FN_area_m2"], 2))
    r(s, "TN area (m2)", round(pix["TN_area_m2"], 2))

    s = "B - Object-level"
    r(s, "GT forest polygons", obj["N_GT"])
    r(s, "Predicted forest polygons", obj["N_Pred"])
    r(s, "TP (objects)", obj["TP"])
    r(s, "FP (objects)", obj["FP"])
    r(s, "FN (objects)", obj["FN"])
    r(s, "Completeness", round(obj["Completeness"], 6), "Object-level recall")
    r(s, "Correctness", round(obj["Correctness"], 6), "Object-level precision")
    r(s, "Quality Rate", round(obj["Quality_Rate"], 6), "TP / (TP+FP+FN)")
    r(s, "AP @ IoU=0.50", round(ap50, 6))
    r(s, "AP @ IoU=0.50:0.95", round(ap5095, 6))

    stat_meta = {
        "IoU": ("C1 - Per-forest IoU", ""),
        "Boundary_IoU": ("C2 - Boundary IoU", ""),
        "Boundary_F1": ("C3 - Boundary F1", ""),
        "Boundary_Precision": ("C4 - Boundary Precision", ""),
        "Boundary_Recall": ("C5 - Boundary Recall", ""),
        "Hausdorff_m": ("C6 - Hausdorff Distance", "metres"),
        "Centroid_dist_m": ("C7 - Centroid Distance", "metres"),
    }
    for key, (section, unit) in stat_meta.items():
        for stat in ("mean", "median", "std", "IQR", "CV", "min", "max", "worst"):
            value = per_forest_stats.get(f"{key}_{stat}", np.nan)
            label = f"{stat.capitalize()}" + (f" ({unit})" if unit else "")
            r(section, label, round(float(value), 6) if not np.isnan(value) else "N/A")

    s = "D - Area Error"
    if matches:
        gt_areas = np.array([m["GT_area_m2"] for m in matches])
        pred_areas = np.array([m["Pred_area_m2"] for m in matches])
        ae = pred_areas - gt_areas
        re = ae / (gt_areas + 1e-9)
        r(s, "Mean Absolute Area Error (m2)", round(float(np.mean(np.abs(ae))), 4))
        r(s, "Mean Relative Area Error", round(float(np.mean(np.abs(re))), 6), f"{np.mean(np.abs(re))*100:.2f}%")
        r(s, "Median Absolute Area Error (m2)", round(float(np.median(np.abs(ae))), 4))
        r(s, "Std of Area Error (m2)", round(float(np.std(ae)), 4))
    else:
        r(s, "Area Error", "N/A", "No matched pairs")

    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False)
    print(f"  Structured CSV saved to:  {output_path}")


def save_readable_report(output_path, console_log, args, pix, obj, ap50, ap5095, per_forest_stats, matches, gt_label, pred_label, study_area):
    report_path = output_path.with_suffix(".txt")
    sep = "=" * 70
    sep2 = "-" * 70
    lines = []
    w = lines.append

    w(sep)
    w("  FOREST MASK EVALUATION REPORT")
    w(sep)
    w(f"  Generated : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w(f"  GT input  : {gt_label}")
    w(f"  Pred input: {pred_label}")
    w(f"  EPSG      : {args.epsg}")
    w(f"  IoU thr.  : {args.iou_threshold}")
    w(f"  Boundary  : {args.boundary_width} m")
    w(sep)

    w("")
    w("  A.  PIXEL-LEVEL METRICS  (area-arithmetic over study area)")
    w(sep2)
    w(f"  Study area                  : {study_area:>15,.1f} m2  ({study_area/1e6:.4f} km2)")
    w("")
    w(f"  IoU (Jaccard)               : {fmt(pix['IoU_Jaccard'])}")
    w(f"  Dice / F1                   : {fmt(pix['F1_Dice'])}")
    w(f"  Precision                   : {fmt(pix['Precision'])}")
    w(f"  Recall                      : {fmt(pix['Recall'])}")
    w(f"  Pixel Accuracy              : {fmt(pix['Pixel_Accuracy'])}")
    w(f"  mIoU                        : {fmt(pix['mIoU'])}")
    w("")
    w(f"  TP area                     : {pix['TP_area_m2']:>15,.2f} m2")
    w(f"  FP area                     : {pix['FP_area_m2']:>15,.2f} m2")
    w(f"  FN area                     : {pix['FN_area_m2']:>15,.2f} m2")
    w(f"  TN area                     : {pix['TN_area_m2']:>15,.2f} m2")

    w("")
    w("  B.  OBJECT-LEVEL METRICS")
    w(sep2)
    w(f"  GT forest polygons          : {obj['N_GT']:>6d}")
    w(f"  Predicted forest polygons   : {obj['N_Pred']:>6d}")
    w(f"  True Positives  (TP)        : {obj['TP']:>6d}")
    w(f"  False Positives (FP)        : {obj['FP']:>6d}")
    w(f"  False Negatives (FN)        : {obj['FN']:>6d}")
    w("")
    w(f"  Completeness (obj. recall)  : {fmt(obj['Completeness'])}")
    w(f"  Correctness  (obj. prec.)   : {fmt(obj['Correctness'])}")
    w(f"  Quality Rate                : {fmt(obj['Quality_Rate'])}")
    w("")
    w(f"  AP @ IoU=0.50               : {fmt(ap50)}")
    w(f"  AP @ IoU=0.50:0.95          : {fmt(ap5095)}")

    sections = {
        "IoU": "C1. Per-forest IoU Statistics",
        "Boundary_IoU": "C2. Boundary IoU (BIoU) Statistics",
        "Boundary_F1": "C3. Boundary F1 (BF1) Statistics",
        "Boundary_Precision": "C4. Boundary Precision Statistics",
        "Boundary_Recall": "C5. Boundary Recall Statistics",
        "Hausdorff_m": "C6. Hausdorff Distance Statistics (metres)",
        "Centroid_dist_m": "C7. Centroid Distance Statistics (metres)",
    }
    for key, title in sections.items():
        w("")
        w(f"  {title}")
        w(sep2)
        if not matches:
            w("  No matched pairs.")
            continue
        for stat in ("mean", "median", "std", "IQR", "CV", "min", "max", "worst"):
            w(f"  {stat:<8}  : {fmt(per_forest_stats.get(f'{key}_{stat}', np.nan))}")

    w("")
    w("  D.  AREA ERROR ANALYSIS  (matched pairs only)")
    w(sep2)
    if matches:
        gt_areas = np.array([m["GT_area_m2"] for m in matches])
        pred_areas = np.array([m["Pred_area_m2"] for m in matches])
        ae = pred_areas - gt_areas
        re = ae / (gt_areas + 1e-9)
        w(f"  Mean Absolute Area Error    : {np.mean(np.abs(ae)):>10.2f} m2")
        w(f"  Mean Relative Area Error    : {np.mean(np.abs(re)):>10.4f}  ({np.mean(np.abs(re))*100:.2f}%)")
        w(f"  Median Absolute Area Error  : {np.median(np.abs(ae)):>10.2f} m2")
        w(f"  Std of Area Error           : {np.std(ae):>10.2f} m2")
    else:
        w("  No matched pairs - skipping.")

    w("")
    w(sep)
    w("  E.  FULL CONSOLE LOG")
    w(sep)
    w("")
    for line in console_log.splitlines():
        w("  " + line)
    w("")
    w(sep)
    w("  END OF REPORT")
    w(sep)

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Readable report saved to: {report_path}")


def evaluate(args):
    output_path = Path(args.output).with_suffix(".csv")
    tee = Tee()
    sys.stdout = tee

    print("\n" + "=" * 60)
    print("Forest Mask Segmentation Evaluation")
    print("=" * 60)

    print("\n[1] Loading inputs...")
    gt_raw, gt_label = load_input(args.gt, args.gt_mask_dir, args.gt_ref_dir, args.min_area_px)
    pred_raw, pred_label = load_input(args.pred, args.pred_mask_dir, args.pred_ref_dir, args.min_area_px)
    print(f"  GT raw:   {len(gt_raw)} rows | CRS: {gt_raw.crs}")
    print(f"  Pred raw: {len(pred_raw)} rows | CRS: {pred_raw.crs}")

    print(f"\n[2] Reprojecting to EPSG:{args.epsg} for metric measurements...")
    gt_projected = gt_raw.to_crs(epsg=args.epsg)
    pred_projected = pred_raw.to_crs(epsg=args.epsg)

    if args.clip_extent:
        print(f"  Clipping inputs to extent: {args.clip_extent}")
        gt_projected = clip_to_extent(gt_projected, args.clip_extent, args.epsg, "GT")
        pred_projected = clip_to_extent(pred_projected, args.clip_extent, args.epsg, "Pred")

    gt = clean_geodataframe(gt_projected, "GT")
    pred = clean_geodataframe(pred_projected, "Pred")

    combined_bounds = unary_union([gt.geometry.unary_union.envelope, pred.geometry.unary_union.envelope]).envelope
    study_area = combined_bounds.area
    print(f"\n[3] Study area: {study_area:,.1f} m2  ({study_area/1e6:.4f} km2)")

    print("\n[4] Computing pixel-level metrics (area arithmetic)...")
    pix = pixel_level_metrics(gt.geometry.unary_union, pred.geometry.unary_union, study_area)
    print(f"  IoU:            {pix['IoU_Jaccard']:.4f}")
    print(f"  Dice / F1:      {pix['F1_Dice']:.4f}")
    print(f"  Precision:      {pix['Precision']:.4f}")
    print(f"  Recall:         {pix['Recall']:.4f}")
    print(f"  Pixel Accuracy: {pix['Pixel_Accuracy']:.4f}")
    print(f"  mIoU:           {pix['mIoU']:.4f}")

    print(f"\n[5] Matching forest polygons (IoU threshold = {args.iou_threshold}, boundary width = {args.boundary_width} m)...")
    matches, _tp_idx, _fp_idx, _fn_idx = match_forest_objects(gt, pred, args.iou_threshold, args.boundary_width)
    obj = object_level_metrics(matches, len(gt), len(pred))
    print(f"  GT forest polygons:   {obj['N_GT']}")
    print(f"  Pred forest polygons: {obj['N_Pred']}")
    print(f"  TP / FP / FN:         {obj['TP']} / {obj['FP']} / {obj['FN']}")
    print(f"  Completeness:         {obj['Completeness']:.4f}")
    print(f"  Correctness:          {obj['Correctness']:.4f}")
    print(f"  Quality rate:         {obj['Quality_Rate']:.4f}")

    print("\n[6] Computing Average Precision...")
    ap50 = compute_ap(matches, len(gt), 0.5)
    ap5095 = float(np.mean([compute_ap(matches, len(gt), t) for t in np.arange(0.5, 1.0, 0.05)]))
    print(f"  AP@0.50:        {ap50:.4f}")
    print(f"  AP@0.50:0.95:   {ap5095:.4f}")

    print("\n[7] Aggregating per-forest boundary & distance statistics...")
    per_forest_stats = {}
    for key in ["IoU", "Boundary_IoU", "Boundary_F1", "Boundary_Precision", "Boundary_Recall", "Hausdorff_m", "Centroid_dist_m"]:
        per_forest_stats.update(stats_summary([m[key] for m in matches] if matches else [], key))
    for key, value in per_forest_stats.items():
        if any(s in key for s in ("mean", "median", "worst")):
            print(f"  {key:<40} {fmt(value)}")

    print("\n[8] Area error analysis (matched pairs)...")
    if matches:
        gt_areas = np.array([m["GT_area_m2"] for m in matches])
        pred_areas = np.array([m["Pred_area_m2"] for m in matches])
        ae = pred_areas - gt_areas
        re = ae / (gt_areas + 1e-9)
        print(f"  Mean Absolute Area Error: {np.mean(np.abs(ae)):.2f} m2")
        print(f"  Mean Relative Area Error: {np.mean(np.abs(re)):.4f}  ({np.mean(np.abs(re))*100:.2f}%)")
    else:
        print("  No matched pairs - skipping area analysis.")

    print("\n[9] Saving reports...")
    sys.stdout = tee._terminal
    console_log = tee.getvalue()

    save_readable_csv(output_path, pix, obj, ap50, ap5095, per_forest_stats, matches, study_area)
    save_readable_report(output_path, console_log, args, pix, obj, ap50, ap5095, per_forest_stats, matches, gt_label, pred_label, study_area)

    if matches:
        detail_path = output_path.with_name(output_path.stem + "_per_forest.csv")
        pd.DataFrame(matches).to_csv(detail_path, index=False)
        print(f"  Per-forest detail saved to: {detail_path}")

    print("\n" + "=" * 60)
    print("Evaluation complete.")
    print("=" * 60)


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate forest/tree-mask segmentation against ground truth.")
    gt = parser.add_mutually_exclusive_group(required=True)
    gt.add_argument("--gt", help="Ground-truth forest shapefile.")
    gt.add_argument("--gt-mask-dir", help="Ground-truth binary mask PNG directory.")
    pred = parser.add_mutually_exclusive_group(required=True)
    pred.add_argument("--pred", help="Predicted forest shapefile.")
    pred.add_argument("--pred-mask-dir", help="Predicted binary mask PNG directory.")
    parser.add_argument("--gt-ref-dir", help="Reference GeoTIFF directory for --gt-mask-dir.")
    parser.add_argument("--pred-ref-dir", help="Reference GeoTIFF directory for --pred-mask-dir.")
    parser.add_argument("--epsg", type=int, default=32637)
    parser.add_argument("--iou-threshold", type=float, default=0.5)
    parser.add_argument("--boundary-width", type=float, default=2.0)
    parser.add_argument("--min-area-px", type=float, default=40.0, help="Minimum mask island size when vectorizing PNG masks.")
    parser.add_argument("--clip-extent", help="GeoJSON/shapefile polygon used to clip both GT and predictions before evaluation.")
    parser.add_argument("--output", default="forest_evaluation.csv")
    return parser.parse_args()


if __name__ == "__main__":
    evaluate(parse_args())
