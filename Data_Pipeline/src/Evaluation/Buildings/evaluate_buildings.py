"""
Building Segmentation Evaluation Script
========================================
Calculates a comprehensive suite of metrics covering:
  - Pixel / overlap metrics  : IoU, Dice/F1, Precision, Recall, Pixel Accuracy, mIoU
  - Boundary metrics         : Boundary IoU (BIoU), Boundary F1 (BF1), Hausdorff distance
  - Object-level metrics     : Completeness, Correctness, Quality, mAP@0.5, Centroid distance
  - Statistical aggregates   : mean, median, std, IQR, CV, worst-case per metric
  - Inter-annotator proxy    : per-building IoU distribution (useful when multiple GT sets exist)

Inputs
------
  --gt    : path to ground truth shapefile (.shp)
  --pred  : path to model prediction shapefile (.shp)
  --epsg  : projected CRS for accurate area/distance calculations (default: 32637 = UTM 37N)
  --iou-threshold  : IoU threshold to count a match as TP for object-level metrics (default: 0.5)
  --boundary-width : width in metres of the boundary band for BIoU / BF1 (default: 2.0)
  --output : path for the CSV report (default: evaluation_report.csv)

Usage
-----
  python evaluate_buildings.py \
      --gt label1/label1.shp \
      --pred buildings1/buildings1.shp \
      --epsg 32637 \
      --iou-threshold 0.5 \
      --boundary-width 2.0 \
      --output evaluation_report.csv
"""

import argparse
import warnings
import sys
import io
import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union
from shapely.geometry import MultiPolygon, Polygon

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────────────────
# Tee: write to both console and an in-memory log
# ─────────────────────────────────────────────────────────────────────────────

class Tee:
    """Redirect stdout to both the terminal and an internal buffer."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ─────────────────────────────────────────────────────────────────────────────

def clean_geodataframe(gdf: gpd.GeoDataFrame, name: str) -> gpd.GeoDataFrame:
    """Drop null / empty geometries, explode multi-polygons to single polygons."""
    before = len(gdf)
    gdf = gdf[~gdf.geometry.isna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()
    gdf = gdf[gdf.geometry.is_valid].copy()
    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].buffer(0)
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)
    print(f"  [{name}] {before} rows → {len(gdf)} valid single polygons after cleaning")
    return gdf


def load_evaluation_boundary(path, epsg):
    """Read an explicit, prediction-independent valid evaluation footprint."""
    boundary = gpd.read_file(path)
    if boundary.crs is None:
        raise ValueError("Evaluation boundary must have a CRS.")
    boundary = boundary.to_crs(epsg=epsg)
    if not boundary.crs.is_projected or any(
        axis.unit_name.lower() not in ("metre", "meter")
        for axis in boundary.crs.axis_info[:2]
    ):
        raise ValueError("Evaluation CRS must be projected in metres.")
    if boundary.empty or boundary.geometry.isna().any():
        raise ValueError("Evaluation boundary must contain valid polygons.")
    if not boundary.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError("Evaluation boundary must be polygonal.")
    if not boundary.geometry.is_valid.all() or boundary.geometry.is_empty.any():
        raise ValueError("Evaluation boundary contains invalid or empty geometry.")
    footprint = unary_union(boundary.geometry)
    if footprint.area <= 0:
        raise ValueError("Evaluation boundary must have positive area.")
    return footprint


def clip_evaluation_objects(gdf, footprint):
    """Clip objects; retain one object per input row even if clipping splits it."""
    clipped = gdf.copy()
    clipped.geometry = clipped.geometry.intersection(footprint)
    # Boundary-only contacts are not evaluated as buildings.
    clipped = clipped.loc[~clipped.geometry.is_empty & (clipped.geometry.area > 0)].copy()
    def polygonal(geom):
        if geom.geom_type in ("Polygon", "MultiPolygon"):
            return geom
        return unary_union([part for part in geom.geoms
                            if part.geom_type in ("Polygon", "MultiPolygon")])
    clipped.geometry = clipped.geometry.map(polygonal)
    return clipped.reset_index(drop=True)


def boundary_band(geom, width: float):
    """Return a polygon representing the boundary band of width `width` metres."""
    outer = geom.buffer(width / 2)
    inner = geom.buffer(-width / 2)
    band = outer.difference(inner)
    return band if not band.is_empty else outer


# ─────────────────────────────────────────────────────────────────────────────
# Pixel-level metrics
# ─────────────────────────────────────────────────────────────────────────────

def pixel_level_metrics(gt_union, pred_union, study_area):
    intersection = gt_union.intersection(pred_union)
    tp = intersection.area if not intersection.is_empty else 0.0
    fp = pred_union.difference(gt_union).area
    fn = gt_union.difference(pred_union).area
    total_area = study_area
    tn = total_area - tp - fp - fn

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) > 0 else 0.0
    iou       = tp / (tp + fp + fn)          if (tp + fp + fn) > 0 else 0.0
    pixel_acc = (tp + tn) / total_area        if total_area > 0 else 0.0
    bg_iou    = tn / (tn + fn + fp)           if (tn + fn + fp) > 0 else 0.0
    miou      = (iou + bg_iou) / 2

    return dict(
        TP_area_m2=tp, FP_area_m2=fp, FN_area_m2=fn, TN_area_m2=tn,
        Precision=precision, Recall=recall,
        F1_Dice=f1, IoU_Jaccard=iou,
        Pixel_Accuracy=pixel_acc, mIoU=miou,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Boundary metrics
# ─────────────────────────────────────────────────────────────────────────────

def boundary_iou(gt_geom, pred_geom, width: float):
    gt_band   = boundary_band(gt_geom,   width)
    pred_band = boundary_band(pred_geom, width)
    inter = gt_band.intersection(pred_band).area
    union = gt_band.union(pred_band).area
    return inter / union if union > 0 else 0.0


def boundary_f1(gt_geom, pred_geom, width: float):
    gt_band = boundary_band(gt_geom, width)
    tp = gt_band.intersection(pred_geom).area
    fp = pred_geom.difference(gt_band).area
    fn = gt_band.difference(pred_geom).area
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return prec, rec, f1


def hausdorff_distance(geom_a, geom_b):
    try:
        return geom_a.hausdorff_distance(geom_b)
    except Exception:
        return np.nan


# ─────────────────────────────────────────────────────────────────────────────
# Object-level matching
# ─────────────────────────────────────────────────────────────────────────────

def match_objects(gt_gdf, pred_gdf, iou_threshold, boundary_width):
    matched_gt   = set()
    matched_pred = set()
    matches      = []

    pred_sindex = pred_gdf.sindex

    for gi, gt_row in gt_gdf.iterrows():
        gt_geom    = gt_row.geometry
        candidates = list(pred_sindex.intersection(gt_geom.bounds))
        if not candidates:
            continue

        best_iou = 0.0
        best_pi  = None
        for pi in candidates:
            pred_geom = pred_gdf.iloc[pi].geometry
            inter = gt_geom.intersection(pred_geom).area
            if inter == 0:
                continue
            union = gt_geom.union(pred_geom).area
            iou   = inter / union if union > 0 else 0.0
            if iou > best_iou:
                best_iou = iou
                best_pi  = pi

        if best_pi is not None and best_iou >= iou_threshold and best_pi not in matched_pred:
            pred_geom = pred_gdf.iloc[best_pi].geometry

            b_iou               = boundary_iou(gt_geom, pred_geom, boundary_width)
            b_prec, b_rec, b_f1 = boundary_f1(gt_geom, pred_geom, boundary_width)
            hd                  = hausdorff_distance(gt_geom, pred_geom)
            centroid_dist       = gt_geom.centroid.distance(pred_geom.centroid)

            matches.append(dict(
                gt_idx=gi, pred_idx=best_pi,
                IoU=best_iou,
                Boundary_IoU=b_iou,
                Boundary_Precision=b_prec,
                Boundary_Recall=b_rec,
                Boundary_F1=b_f1,
                Hausdorff_m=hd,
                Centroid_dist_m=centroid_dist,
                GT_area_m2=gt_geom.area,
                Pred_area_m2=pred_geom.area,
            ))
            matched_gt.add(gi)
            matched_pred.add(best_pi)

    tp_indices = [m["gt_idx"]   for m in matches]
    fp_indices = [i for i in range(len(pred_gdf)) if i not in matched_pred]
    fn_indices = [i for i in range(len(gt_gdf))   if i not in matched_gt]

    return matches, tp_indices, fp_indices, fn_indices


# ─────────────────────────────────────────────────────────────────────────────
# Object-level aggregate metrics
# ─────────────────────────────────────────────────────────────────────────────

def object_level_metrics(matches, n_gt, n_pred):
    n_tp = len(matches)
    n_fp = n_pred - n_tp
    n_fn = n_gt  - n_tp
    completeness = n_tp / n_gt   if n_gt   > 0 else 0.0
    correctness  = n_tp / n_pred if n_pred > 0 else 0.0
    quality      = n_tp / (n_tp + n_fp + n_fn) if (n_tp + n_fp + n_fn) > 0 else 0.0
    return dict(
        N_GT=n_gt, N_Pred=n_pred,
        TP=n_tp, FP=n_fp, FN=n_fn,
        Completeness=completeness,
        Correctness=correctness,
        Quality_Rate=quality,
    )


def compute_ap(matches, n_gt, iou_threshold):
    if n_gt == 0:
        return 0.0
    sorted_matches = sorted(matches, key=lambda m: m["IoU"], reverse=True)
    tp_arr = np.zeros(len(sorted_matches))
    fp_arr = np.zeros(len(sorted_matches))
    seen_gt = set()
    for i, m in enumerate(sorted_matches):
        if m["IoU"] >= iou_threshold and m["gt_idx"] not in seen_gt:
            tp_arr[i] = 1
            seen_gt.add(m["gt_idx"])
        else:
            fp_arr[i] = 1
    cum_tp        = np.cumsum(tp_arr)
    cum_fp        = np.cumsum(fp_arr)
    recall_arr    = cum_tp / n_gt
    precision_arr = cum_tp / (cum_tp + cum_fp + 1e-9)
    ap = 0.0
    for t in np.linspace(0, 1, 101):
        prec_at_t = precision_arr[recall_arr >= t]
        ap += prec_at_t.max() if len(prec_at_t) > 0 else 0.0
    return ap / 101


# ─────────────────────────────────────────────────────────────────────────────
# Statistical summary helper
# ─────────────────────────────────────────────────────────────────────────────

def stats_summary(values, name):
    arr = np.array(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0:
        return {f"{name}_mean": np.nan, f"{name}_median": np.nan,
                f"{name}_std":  np.nan, f"{name}_IQR":    np.nan,
                f"{name}_CV":   np.nan, f"{name}_min":    np.nan,
                f"{name}_max":  np.nan, f"{name}_worst":  np.nan}
    q1, q3 = np.percentile(arr, [25, 75])
    mean   = arr.mean()
    is_dist = "dist" in name.lower() or "hausdorff" in name.lower()
    return {
        f"{name}_mean":   mean,
        f"{name}_median": np.median(arr),
        f"{name}_std":    arr.std(),
        f"{name}_IQR":    q3 - q1,
        f"{name}_CV":     arr.std() / mean if mean != 0 else np.nan,
        f"{name}_min":    arr.min(),
        f"{name}_max":    arr.max(),
        f"{name}_worst":  arr.max() if is_dist else arr.min(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Report helpers
# ─────────────────────────────────────────────────────────────────────────────

def fmt(value, decimals=4):
    """Format a numeric value for display."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def save_readable_report(output_path: Path, console_log: str, args_dict: dict,
                          pix, obj, ap50, ap5095,
                          per_building_stats, matches,
                          gt_path, pred_path, study_area):
    """
    Write a well-structured, human-readable .txt report that mirrors
    everything shown on the console plus clearly labelled sections.
    """
    report_path = output_path.with_suffix(".txt")
    sep  = "=" * 70
    sep2 = "-" * 70
    now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = []
    w = lines.append  # shorthand

    w(sep)
    w("  BUILDING SEGMENTATION EVALUATION REPORT")
    w(sep)
    w(f"  Generated : {now}")
    w(f"  GT file   : {gt_path}")
    w(f"  Pred file : {pred_path}")
    w(f"  Evaluation boundary: {args_dict['evaluation_boundary']}")
    w("  Boundary policy: clip polygons; retain one object per cleaned input row.")
    w(f"  EPSG      : {args_dict['epsg']}")
    w(f"  IoU thr.  : {args_dict['iou_threshold']}")
    w(f"  Boundary  : {args_dict['boundary_width']} m")
    w(sep)

    # ── A. Pixel-level ────────────────────────────────────────────
    w("")
    w("  A.  AREA-BASED METRICS  (area-arithmetic over study area)")
    w(sep2)
    w(f"  Study area                  : {study_area:>15,.1f} m²  "
      f"({study_area/1e6:.4f} km²)")
    w("")
    w(f"  IoU (Jaccard)               : {fmt(pix['IoU_Jaccard'])}")
    w(f"  Dice / F1                   : {fmt(pix['F1_Dice'])}")
    w(f"  Precision                   : {fmt(pix['Precision'])}")
    w(f"  Recall                      : {fmt(pix['Recall'])}")
    w(f"  Pixel Accuracy              : {fmt(pix['Pixel_Accuracy'])}")
    w(f"  mIoU                        : {fmt(pix['mIoU'])}")
    w("")
    w(f"  TP area                     : {pix['TP_area_m2']:>15,.2f} m²")
    w(f"  FP area                     : {pix['FP_area_m2']:>15,.2f} m²")
    w(f"  FN area                     : {pix['FN_area_m2']:>15,.2f} m²")
    w(f"  TN area                     : {pix['TN_area_m2']:>15,.2f} m²")

    # ── B. Object-level ───────────────────────────────────────────
    w("")
    w("  B.  OBJECT-LEVEL METRICS")
    w(sep2)
    w(f"  GT buildings                : {obj['N_GT']:>6d}")
    w(f"  Predicted buildings         : {obj['N_Pred']:>6d}")
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

    # ── C. Per-building statistics ────────────────────────────────
    stat_sections = {
        "IoU": "C1. Per-building IoU Statistics",
        "Boundary_IoU": "C2. Boundary IoU (BIoU) Statistics",
        "Boundary_F1": "C3. Boundary F1 (BF1) Statistics",
        "Boundary_Precision": "C4. Boundary Precision Statistics",
        "Boundary_Recall": "C5. Boundary Recall Statistics",
        "Hausdorff_m": "C6. Hausdorff Distance Statistics (metres)",
        "Centroid_dist_m": "C7. Centroid Distance Statistics (metres)",
    }

    for key, title in stat_sections.items():
        pass  # just iterate below

    for key, title in stat_sections.items():
        w("")
        w(f"  {title}")
        w(sep2)
        if not matches:
            w("  No matched pairs.")
            continue
        for stat in ("mean", "median", "std", "IQR", "CV", "min", "max", "worst"):
            k = f"{key}_{stat}"
            v = per_building_stats.get(k, np.nan)
            w(f"  {stat:<8}  : {fmt(v)}")

    # ── D. Area error ─────────────────────────────────────────────
    w("")
    w("  D.  AREA ERROR ANALYSIS  (matched pairs only)")
    w(sep2)
    if matches:
        gt_areas   = np.array([m["GT_area_m2"]   for m in matches])
        pred_areas = np.array([m["Pred_area_m2"] for m in matches])
        ae  = pred_areas - gt_areas
        re  = ae / (gt_areas + 1e-9)
        w(f"  Mean Absolute Area Error    : {np.mean(np.abs(ae)):>10.2f} m²")
        w(f"  Mean Relative Area Error    : {np.mean(np.abs(re)):>10.4f}  "
          f"({np.mean(np.abs(re))*100:.2f}%)")
        w(f"  Median Absolute Area Error  : {np.median(np.abs(ae)):>10.2f} m²")
        w(f"  Std of Area Error           : {np.std(ae):>10.2f} m²")
    else:
        w("  No matched pairs — skipping.")

    # ── E. Full console log ───────────────────────────────────────
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
    return report_path


def save_readable_csv(output_path: Path, pix, obj, ap50, ap5095,
                      per_building_stats, matches, study_area):
    """
    Save a clearly sectioned, labelled CSV — one metric per row with a
    Section, Metric, Value, and Notes column.
    """
    rows = []

    def r(section, metric, value, notes=""):
        rows.append({"Section": section, "Metric": metric,
                     "Value": value, "Notes": notes})

    # A — pixel
    S = "A - Area-based"
    r(S, "Study Area (m²)",    round(study_area, 2),        "Explicit evaluation boundary; GT and predictions clipped")
    r(S, "IoU (Jaccard)",      round(pix["IoU_Jaccard"], 6), "Intersection over Union")
    r(S, "Dice / F1",          round(pix["F1_Dice"], 6),     "2*TP / (2*TP+FP+FN)")
    r(S, "Precision",          round(pix["Precision"], 6),   "TP / (TP+FP)")
    r(S, "Recall",             round(pix["Recall"], 6),      "TP / (TP+FN)")
    r(S, "Area-based Accuracy",     round(pix["Pixel_Accuracy"], 6), "(TP+TN) / total area")
    r(S, "mIoU",               round(pix["mIoU"], 6),        "Mean of building-IoU and background-IoU")
    r(S, "TP area (m²)",       round(pix["TP_area_m2"], 2))
    r(S, "FP area (m²)",       round(pix["FP_area_m2"], 2))
    r(S, "FN area (m²)",       round(pix["FN_area_m2"], 2))
    r(S, "TN area (m²)",       round(pix["TN_area_m2"], 2))

    # B — object
    S = "B - Object-level"
    r(S, "GT buildings",       obj["N_GT"])
    r(S, "Predicted buildings",obj["N_Pred"])
    r(S, "TP (objects)",       obj["TP"])
    r(S, "FP (objects)",       obj["FP"])
    r(S, "FN (objects)",       obj["FN"])
    r(S, "Completeness",       round(obj["Completeness"], 6), "Object-level recall")
    r(S, "Correctness",        round(obj["Correctness"], 6),  "Object-level precision")
    r(S, "Quality Rate",       round(obj["Quality_Rate"], 6), "TP / (TP+FP+FN)")
    r(S, "AP @ IoU=0.50",      round(ap50,   6))
    r(S, "AP @ IoU=0.50:0.95", round(ap5095, 6))

    # C — per-building stats
    stat_meta = {
        "IoU":               ("C1 - Per-building IoU",        ""),
        "Boundary_IoU":      ("C2 - Boundary IoU",            ""),
        "Boundary_F1":       ("C3 - Boundary F1",             ""),
        "Boundary_Precision":("C4 - Boundary Precision",      ""),
        "Boundary_Recall":   ("C5 - Boundary Recall",         ""),
        "Hausdorff_m":       ("C6 - Hausdorff Distance",      "metres"),
        "Centroid_dist_m":   ("C7 - Centroid Distance",       "metres"),
    }
    for key, (section, unit) in stat_meta.items():
        for stat in ("mean", "median", "std", "IQR", "CV", "min", "max", "worst"):
            k = f"{key}_{stat}"
            v = per_building_stats.get(k, np.nan)
            label = f"{stat.capitalize()}" + (f" ({unit})" if unit else "")
            val   = round(float(v), 6) if not np.isnan(v) else "N/A"
            r(section, label, val)

    # D — area errors
    S = "D - Area Error"
    if matches:
        gt_areas   = np.array([m["GT_area_m2"]   for m in matches])
        pred_areas = np.array([m["Pred_area_m2"] for m in matches])
        ae = pred_areas - gt_areas
        re = ae / (gt_areas + 1e-9)
        r(S, "Mean Absolute Area Error (m²)",    round(float(np.mean(np.abs(ae))), 4))
        r(S, "Mean Relative Area Error",         round(float(np.mean(np.abs(re))), 6),
            f"{np.mean(np.abs(re))*100:.2f}%")
        r(S, "Median Absolute Area Error (m²)",  round(float(np.median(np.abs(ae))), 4))
        r(S, "Std of Area Error (m²)",           round(float(np.std(ae)), 4))
    else:
        r(S, "Area Error", "N/A", "No matched pairs")

    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False)
    print(f"  Structured CSV saved to:  {output_path}")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Main evaluation pipeline
# ─────────────────────────────────────────────────────────────────────────────

def evaluate(gt_path, pred_path, epsg, iou_threshold, boundary_width, output_path, evaluation_boundary):
    # Always ensure the base output path ends with .csv so that
    # .with_suffix() and .with_name() calls produce correct sibling paths.
    output_path = Path(output_path).with_suffix(".csv")

    footprint = load_evaluation_boundary(evaluation_boundary, epsg)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Capture everything printed to the console
    tee = Tee()
    sys.stdout = tee

    print("\n" + "=" * 60)
    print("Building Segmentation Evaluation")
    print("=" * 60)

    # ── Load & clean ──────────────────────────────────────────────
    print("\n[1] Loading shapefiles...")
    gt_raw   = gpd.read_file(gt_path)
    pred_raw = gpd.read_file(pred_path)
    print(f"  GT raw:   {len(gt_raw)} rows | CRS: {gt_raw.crs}")
    print(f"  Pred raw: {len(pred_raw)} rows | CRS: {pred_raw.crs}")

    print(f"\n[2] Reprojecting to EPSG:{epsg} for metric measurements...")
    gt_raw   = gt_raw.to_crs(epsg=epsg)
    pred_raw = pred_raw.to_crs(epsg=epsg)
    gt   = clean_geodataframe(gt_raw,   "GT")
    pred = clean_geodataframe(pred_raw, "Pred")

    gt = clip_evaluation_objects(gt, footprint)
    pred = clip_evaluation_objects(pred, footprint)
    study_area = footprint.area
    print(f"  Evaluation boundary: {Path(evaluation_boundary).resolve()}")
    print("  Boundary policy: clip polygons; retain one object per cleaned input row.")
    gpd.GeoDataFrame(geometry=[footprint], crs=f"EPSG:{epsg}").to_file(
        output_path.with_name(output_path.stem + "_boundary.geojson"), driver="GeoJSON"
    )
    print(f"\n[3] Study area: {study_area:,.1f} m²  ({study_area/1e6:.4f} km²)")

    # ── Pixel-level ───────────────────────────────────────────────
    print("\n[4] Computing area-based metrics (area arithmetic)...")
    gt_union   = gt.geometry.unary_union
    pred_union = pred.geometry.unary_union
    pix = pixel_level_metrics(gt_union, pred_union, study_area)
    print(f"  IoU:            {pix['IoU_Jaccard']:.4f}")
    print(f"  Dice / F1:      {pix['F1_Dice']:.4f}")
    print(f"  Precision:      {pix['Precision']:.4f}")
    print(f"  Recall:         {pix['Recall']:.4f}")
    print(f"  Area Accuracy: {pix['Pixel_Accuracy']:.4f}")
    print(f"  mIoU:           {pix['mIoU']:.4f}")

    # ── Object-level ──────────────────────────────────────────────
    print(f"\n[5] Matching objects (IoU threshold = {iou_threshold}, "
          f"boundary width = {boundary_width} m)...")
    matches, tp_idx, fp_idx, fn_idx = match_objects(
        gt, pred, iou_threshold, boundary_width
    )
    obj = object_level_metrics(matches, len(gt), len(pred))
    print(f"  GT buildings:   {obj['N_GT']}")
    print(f"  Pred buildings: {obj['N_Pred']}")
    print(f"  TP / FP / FN:   {obj['TP']} / {obj['FP']} / {obj['FN']}")
    print(f"  Completeness:   {obj['Completeness']:.4f}")
    print(f"  Correctness:    {obj['Correctness']:.4f}")
    print(f"  Quality rate:   {obj['Quality_Rate']:.4f}")

    # ── AP ────────────────────────────────────────────────────────
    print("\n[6] Computing Average Precision...")
    ap50   = compute_ap(matches, len(gt), 0.5)
    ap5095 = np.mean([compute_ap(matches, len(gt), t)
                      for t in np.arange(0.5, 1.0, 0.05)])
    print(f"  AP@0.50:        {ap50:.4f}")
    print(f"  AP@0.50:0.95:   {ap5095:.4f}")

    # ── Per-match stats ───────────────────────────────────────────
    print("\n[7] Aggregating per-building boundary & distance statistics...")
    metric_keys = ["IoU", "Boundary_IoU", "Boundary_F1",
                   "Boundary_Precision", "Boundary_Recall",
                   "Hausdorff_m", "Centroid_dist_m"]
    per_building_stats = {}
    for key in metric_keys:
        vals = [m[key] for m in matches] if matches else []
        per_building_stats.update(stats_summary(vals, key))

    for k, v in per_building_stats.items():
        if any(s in k for s in ("mean", "median", "worst")):
            print(f"  {k:<40} {fmt(v)}")

    # ── Area errors ───────────────────────────────────────────────
    print("\n[8] Area error analysis (matched pairs)...")
    if matches:
        gt_areas   = np.array([m["GT_area_m2"]   for m in matches])
        pred_areas = np.array([m["Pred_area_m2"] for m in matches])
        ae  = pred_areas - gt_areas
        re  = ae / (gt_areas + 1e-9)
        mae = np.mean(np.abs(ae))
        mre = np.mean(np.abs(re))
        print(f"  Mean Absolute Area Error: {mae:.2f} m²")
        print(f"  Mean Relative Area Error: {mre:.4f}  ({mre*100:.2f}%)")
    else:
        mae = mre = np.nan
        print("  No matched pairs — skipping area analysis.")

    # ── Save outputs ──────────────────────────────────────────────
    print(f"\n[9] Saving reports...")

    # Restore stdout before printing final messages
    sys.stdout = tee._terminal
    console_log = tee.getvalue()

    # Structured CSV
    save_readable_csv(
        output_path, pix, obj, ap50, ap5095,
        per_building_stats, matches, study_area
    )

    # Human-readable TXT report (includes full console log)
    args_dict = dict(epsg=epsg, iou_threshold=iou_threshold,
                     boundary_width=boundary_width, evaluation_boundary=str(Path(evaluation_boundary).resolve()))
    save_readable_report(
        output_path, console_log, args_dict,
        pix, obj, ap50, ap5095,
        per_building_stats, matches,
        gt_path, pred_path, study_area
    )

    # Per-building detail CSV
    if matches:
        detail_path = output_path.with_name(
            output_path.stem + "_per_building.csv"
        )
        pd.DataFrame(matches).to_csv(detail_path, index=False)
        print(f"  Per-building detail saved to: {detail_path}")

    print("\n" + "=" * 60)
    print("Evaluation complete.")
    print("=" * 60)

    return dict(
        pix=pix, obj=obj, ap50=ap50, ap5095=ap5095,
        per_building_stats=per_building_stats, matches=matches,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Evaluate a building segmentation model against ground truth shapefiles."
    )
    parser.add_argument("--evaluation-boundary", required=True,
                        help="Common valid evaluation footprint (GeoJSON/shapefile); identical for all models.")
    parser.add_argument("--gt",   required=True)
    parser.add_argument("--pred", required=True)
    parser.add_argument("--epsg", type=int, default=32637)
    parser.add_argument("--iou-threshold",  type=float, default=0.5)
    parser.add_argument("--boundary-width", type=float, default=2.0)
    parser.add_argument("--output", default="evaluation_report.csv")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    evaluate(
        gt_path=args.gt,
        pred_path=args.pred,
        epsg=args.epsg,
        iou_threshold=args.iou_threshold,
        boundary_width=args.boundary_width,
        output_path=args.output,
        evaluation_boundary=args.evaluation_boundary,
    )