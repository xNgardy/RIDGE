import os
import time
from math import pi, sin, cos, sqrt, atan, exp
import numpy
from shapely import geometry, ops

# from PIL import Image, ImageDraw, ImageFilter
import O4_DEM_Utils as DEM
import O4_UI_Utils as UI
import O4_OSM_Utils as OSM
import O4_Vector_Utils as VECT
import O4_File_Names as FNAMES
import O4_Geo_Utils as GEO
import O4_Local_Data as LOCAL_DATA

good_imagery_list = ()

################################################################################
def build_poly_file(tile):
    if UI.is_working:
        return 0
    UI.is_working = 1
    UI.red_flag = 0
    # in case that was forgotten by the user
    tile.iterate = 0
    # update the lat/lon scaling factor in VECT
    VECT.scalx = cos((tile.lat + 0.5) * pi / 180)
    # Let's go !
    UI.logprint(
        "Step 1 for tile lat=", tile.lat, ", lon=", tile.lon, ": starting."
    )
    UI.vprint(
        0,
        "\nStep 1 : Building vector data for tile "
        + FNAMES.short_latlon(tile.lat, tile.lon)
        + " : \n--------\n",
    )
    timer = time.time()

    if not os.path.exists(tile.build_dir):
        os.makedirs(tile.build_dir)
    if not os.path.exists(FNAMES.osm_dir(tile.lat, tile.lon)):
        os.makedirs(FNAMES.osm_dir(tile.lat, tile.lon))
    node_file = FNAMES.input_node_file(tile)
    poly_file = FNAMES.input_poly_file(tile)
    vector_map = VECT.Vector_Map()

    UI.vprint(1, "   Loading elevation data.")
    tile.dem = DEM.DEM(
        tile.lat,
        tile.lon,
        tile.custom_dem,
        tile.fill_nodata or "to zero",
        info_only=False,
    )

    if UI.red_flag:
        UI.exit_message_and_bottom_line()
        return 0

    # Sea
    include_sea(vector_map, tile)
    UI.vprint(
        1, "   Number of edges at this point:", len(vector_map.dico_edges)
    )

    if UI.red_flag:
        UI.exit_message_and_bottom_line()
        return 0

    # Water
    include_water(vector_map, tile)
    UI.vprint(
        1, "   Number of edges at this point:", len(vector_map.dico_edges)
    )

    if UI.red_flag:
        UI.exit_message_and_bottom_line()
        return 0

    # Orthogrid
    UI.vprint(0, "-> Inserting edges related to the orthophotos grid")
    xgrid = set()  # x coordinates of vertical grid lines
    ygrid = set()  # y coordinates of horizontal grid lines
    (til_xul, til_yul) = GEO.wgs84_to_orthogrid(
        tile.lat + 1, tile.lon, tile.mesh_zl
    )
    (til_xlr, til_ylr) = GEO.wgs84_to_orthogrid(
        tile.lat, tile.lon + 1, tile.mesh_zl
    )
    for til_x in range(til_xul + 16, til_xlr + 1, 16):
        pos_x = til_x / (2 ** (tile.mesh_zl - 1)) - 1
        xgrid.add(pos_x * 180 - tile.lon)
        #print("x", pos_x * 180 - tile.lon)
    for til_y in range(til_yul + 16, til_ylr + 1, 16):
        pos_y = 1 - (til_y) / (2 ** (tile.mesh_zl - 1))
        ygrid.add(360 / pi * atan(exp(pi * pos_y)) - 90 - tile.lat)
        #print("y", (360 / pi * atan(exp(pi * pos_y)) - 90 - tile.lat))

    xgrid.add(0)
    xgrid.add(1)
    ygrid.add(0)
    ygrid.add(1)
    xgrid = list(sorted(xgrid))
    ygrid = list(sorted(ygrid))
    eps = 2 ** -5
    ortho_network = geometry.MultiLineString(
        [geometry.LineString([(x, 0.0 - eps), (x, 1.0 + eps)]) for x in xgrid]
        + [geometry.LineString([(0.0 - eps, y), (1.0 + eps, y)]) for y in ygrid]
    )
    vector_map.encode_MultiLineString(
        ortho_network, tile.dem.alt_vec, "DUMMY", check=True, skip_cut=True
    )

    if UI.red_flag:
        UI.exit_message_and_bottom_line()
        return 0

    # Gluing edges
    UI.vprint(0, "-> Inserting additional boundary edges for gluing")
    segs = 2048
    gluing_network = geometry.MultiLineString(
        [
            geometry.LineString(
                [(x, 0) for x in numpy.arange(0, segs + 1) / segs]
            ),
            geometry.LineString(
                [(x, 1) for x in numpy.arange(0, segs + 1) / segs]
            ),
            geometry.LineString(
                [(0, y) for y in numpy.arange(0, segs + 1) / segs]
            ),
            geometry.LineString(
                [(1, y) for y in numpy.arange(0, segs + 1) / segs]
            ),
        ]
    )
    vector_map.encode_MultiLineString(
        gluing_network, tile.dem.alt_vec, "DUMMY", check=True, skip_cut=True
    )

    if UI.red_flag:
        UI.exit_message_and_bottom_line()
        return 0
    UI.vprint(0, "-> Transcription to the files ", poly_file, "and .node")
    if not vector_map.seeds:
        if tile.dem.alt_dem.max() >= 1:
            vector_map.seeds["SEA"] = [numpy.array([1000, 1000])]
        else:
            vector_map.seeds["SEA"] = [numpy.array([0.5, 0.5])]
    vector_map.snap_to_grid(9) 
    vector_map.write_node_file(node_file)
    vector_map.write_poly_file(poly_file)

    UI.vprint(
        1, "\nFinal number of constrained edges :", len(vector_map.dico_edges)
    )
    UI.timings_and_bottom_line(timer)
    UI.logprint(
        "Step 1 for tile lat=", tile.lat, ", lon=", tile.lon, ": normal exit."
    )
    return 1


################################################################################
def include_sea(vector_map, tile):
    UI.vprint(0, "-> Dealing with coastline")
    sea_layer = OSM.OSM_layer()
    custom_source = False
    custom_coastline = FNAMES.custom_coastline(tile.lat, tile.lon)
    custom_coastline_dir = FNAMES.custom_coastline_dir(tile.lat, tile.lon)

    # Check for local data mode
    local_data_root = getattr(UI, 'local_data_root', None)

    if os.path.isfile(custom_coastline):
        UI.vprint(1, "    * User defined custom coastline data detected.")
        sea_layer.update_dicosm(
            custom_coastline, input_tags=None, target_tags=None
        )
        custom_source = True
    elif os.path.isdir(custom_coastline_dir):
        UI.vprint(
            1,
            "    * User defined custom coastline data detected ",
            "(multiple files).",
        )
        for osm_file in os.listdir(custom_coastline_dir):
            UI.vprint(2, "      ", osm_file)
            sea_layer.update_dicosm(
                os.path.join(custom_coastline_dir, osm_file),
                input_tags=None,
                target_tags=None,
            )
            sea_layer.write_to_file(custom_coastline)
        custom_source = True
    elif local_data_root:
        # Use local coastline data from Shapefile
        UI.vprint(1, "    * Loading coastline data from local Shapefile")
        try:
            water_features = LOCAL_DATA.get_local_water_features(tile.lat, tile.lon, local_data_root)
            if water_features:
                # Convert water boundary to coastline
                for idx, feature in enumerate(water_features):
                    geom = feature['geometry']
                    osmid = idx
                    # Store boundary lines as coastline
                    if geom.geom_type == 'Polygon':
                        sea_layer.dico_ways[osmid] = geom.exterior.coords[:]
                    elif geom.geom_type == 'MultiPolygon':
                        for sub_idx, poly in enumerate(geom.geoms):
                            sub_osmid = idx * 1000 + sub_idx
                            sea_layer.dico_ways[sub_osmid] = poly.exterior.coords[:]
                UI.vprint(1, f"    * Loaded {len(water_features)} coastline features from local data")
                custom_source = True
            else:
                UI.vprint(1, "    * No local coastline data found, skipping sea")
                return 1
        except Exception as e:
            UI.vprint(1, f"    * Error loading local coastline data: {e}, continuing")
            return 1
    else:
        queries = ['way["natural"="coastline"]']
        tags_of_interest = []
        if not OSM.OSM_queries_to_OSM_layer(
            queries,
            sea_layer,
            tile.lat,
            tile.lon,
            tags_of_interest,
            cached_suffix="coastline",
        ):
            return 0
    coastline = OSM.OSM_to_MultiLineString(sea_layer, tile.lat, tile.lon)
    if not coastline.is_empty:
        # 1) encoding the coastline
        UI.vprint(1, "    * Encoding coastline.")
        vector_map.encode_MultiLineString(
            VECT.cut_to_tile(coastline, strictly_inside=True),
            tile.dem.alt_vec,
            "SEA",
            check=True,
            refine=False,
        )
        UI.vprint(3, "...done.")
        # 2) finding seeds (transform multilinestring coastline to polygon
        # coastline linemerge being expensive we first set aside what is
        # already known to be closed loops
        UI.vprint(1, "    * Reconstructing its topology.")
        loops = geometry.MultiLineString(
            [line for line in coastline.geoms if line.is_ring]
        )
        remainder = VECT.ensure_MultiLineString(
            VECT.cut_to_tile(
                geometry.MultiLineString(
                    [line for line in coastline.geoms if not line.is_ring]
                ),
                strictly_inside=True,
            )
        )
        UI.vprint(3, "Linemerge...")
        if not remainder.is_empty:
            remainder = VECT.ensure_MultiLineString(ops.linemerge(remainder))
        UI.vprint(3, "...done.")
        coastline = geometry.MultiLineString(
            list(remainder.geoms) + list(loops.geoms)
        )
        sea_area = VECT.ensure_MultiPolygon(
            VECT.coastline_to_MultiPolygon(
                coastline, tile.lat, tile.lon, custom_source
            )
        )
        if sea_area.geoms:
            UI.vprint(
                1, "      Found ", len(sea_area.geoms), "contiguous patch(es)."
            )
        for polygon in sea_area.geoms:
            seed = numpy.array(polygon.representative_point().coords[0])
            if "SEA" in vector_map.seeds:
                vector_map.seeds["SEA"].append(seed)
            else:
                vector_map.seeds["SEA"] = [seed]


################################################################################
def include_water(vector_map, tile):
    large_lake_threshold = (
        tile.max_area * 1e6 / (GEO.lat_to_m * GEO.lon_to_m(tile.lat + 0.5))
    )

    def filter_large_lakes(pol, osmid, dicosmtags):
        if pol.area < large_lake_threshold:
            return False
        area = int(pol.area * GEO.lat_to_m * GEO.lon_to_m(tile.lat + 0.5) / 1e6)
        if (osmid in dicosmtags) and ("name" in dicosmtags[osmid]):
            if dicosmtags[osmid]["name"] in good_imagery_list:
                UI.vprint(
                    1,
                    "      * ",
                    dicosmtags[osmid]["name"],
                    "kept will complete imagery although it is",
                    area,
                    "km^2.",
                )
                return False
            else:
                UI.vprint(
                    1,
                    "      * ",
                    dicosmtags[osmid]["name"],
                    "will be masked like the sea due to its large area of",
                    area,
                    "km^2.",
                )
                return True
        else:
            pt = (
                pol.exterior.coords[0]
                if "Multi" not in pol.geom_type
                else pol.geoms[0].exterior.coords[0]
            )
            UI.vprint(
                1,
                "      * ",
                "Some large OSM water patch close to lat=",
                "{:.2f}".format(pt[1] + tile.lon),
                "lon=",
                "{:.2f}".format(pt[0] + tile.lat),
                "will be masked due to its large area of",
                area,
                "km^2.",
            )
            return True

    UI.vprint(0, "-> Dealing with inland water")
    water_layer = OSM.OSM_layer()
    custom_water = FNAMES.custom_water(tile.lat, tile.lon)
    custom_water_dir = FNAMES.custom_water_dir(tile.lat, tile.lon)

    # Check for local data mode
    local_data_root = getattr(UI, 'local_data_root', None)

    if os.path.isfile(custom_water):
        UI.vprint(1, "    * User defined custom water data detected.")
        water_layer.update_dicosm(
            custom_water, input_tags=None, target_tags=None
        )
    elif os.path.isdir(custom_water_dir):
        UI.vprint(
            1, "    * User defined custom water data detected (multiple files)."
        )
        for osm_file in os.listdir(custom_water_dir):
            UI.vprint(2, "      ", osm_file)
            water_layer.update_dicosm(
                os.path.join(custom_water_dir, osm_file),
                input_tags=None,
                target_tags=None,
            )
            water_layer.write_to_file(custom_water)
    elif local_data_root:
        # Use local water data from Shapefile
        UI.vprint(1, "    * Loading water data from local Shapefile")
        try:
            water_features = LOCAL_DATA.get_local_water_features(tile.lat, tile.lon, local_data_root)
            if water_features:
                # Convert Shapefile geometries to OSM layer format
                for idx, feature in enumerate(water_features):
                    geom = feature['geometry']
                    osmid = idx
                    # Add to water_layer (simplified - just store geometry)
                    if geom.geom_type == 'Polygon':
                        water_layer.dico_ways[osmid] = geom.exterior.coords[:]
                        water_layer.dicosm[osmid] = {'name': 'local_water'}
                    elif geom.geom_type == 'MultiPolygon':
                        for sub_idx, poly in enumerate(geom.geoms):
                            sub_osmid = idx * 1000 + sub_idx
                            water_layer.dico_ways[sub_osmid] = poly.exterior.coords[:]
                            water_layer.dicosm[sub_osmid] = {'name': 'local_water'}
                UI.vprint(1, f"    * Loaded {len(water_features)} water features from local data")
            else:
                UI.vprint(1, "    * No local water data found, skipping water")
                water_area = geometry.MultiPolygon()
                sea_equiv_area = geometry.MultiPolygon()
                # VECT.add_water_to_Vector_Map(vector_map, water_area, sea_equiv_area)
                return 1
        except Exception as e:
            UI.vprint(1, f"    * Error loading local water data: {e}, continuing")
            water_area = geometry.MultiPolygon()
            sea_equiv_area = geometry.MultiPolygon()
            # VECT.add_water_to_Vector_Map(vector_map, water_area, sea_equiv_area)
            return 1
    else:
        queries = [
            'rel["natural"="water"]',
            'rel["waterway"="riverbank"]',
            'way["natural"="water"]',
            'way["waterway"="riverbank"]',
            'way["waterway"="dock"]',
        ]
        tags_of_interest = ["name"]
        if not OSM.OSM_queries_to_OSM_layer(
            queries,
            water_layer,
            tile.lat,
            tile.lon,
            tags_of_interest,
            cached_suffix="water",
        ):
            return 0
    UI.vprint(1, "    * Building water multipolygon.")
    (water_area, sea_equiv_area) = OSM.OSM_to_MultiPolygon(
        water_layer, tile.lat, tile.lon, filter_large_lakes
    )
    if not water_area.is_empty:
        UI.vprint(1, "      Cleaning it.")
        try:
            (idx_water, dico_water) = VECT.MultiPolygon_to_Indexed_Polygons(
                water_area, merge_overlappings=tile.clean_bad_geometries
            )
        except:
            return 0
        UI.vprint(
            2, "      Number of water Multipolygons : " + str(len(dico_water))
        )
        UI.vprint(1, "      Encoding it.")
        vector_map.encode_MultiPolygon(
            dico_water,
            tile.dem.alt_vec,
            "WATER",
            area_limit=tile.min_area / 10000,
            simplify=tile.water_simplification * GEO.m_to_lat,
            check=True,
        )
    if not sea_equiv_area.is_empty:
        UI.vprint(
            1, "      Separate treatment for larger pieces requiring masks."
        )
        try:
            (idx_water, dico_water) = VECT.MultiPolygon_to_Indexed_Polygons(
                sea_equiv_area, merge_overlappings=tile.clean_bad_geometries
            )
        except:
            return 0
        UI.vprint(
            2, "      Number of water Multipolygons : " + str(len(dico_water))
        )
        UI.vprint(1, "      Encoding them.")
        vector_map.encode_MultiPolygon(
            dico_water,
            tile.dem.alt_vec,
            "SEA_EQUIV",
            area_limit=tile.min_area / 10000,
            simplify=tile.water_simplification * GEO.m_to_lat,
            check=True,
        )
    return 1


################################################################################
def keep_obj8(
    lat_anchor,
    lon_anchor,
    alt_anchor,
    heading_anchor,
    objfile_name,
    vector_map,
    tile,
):
    dico_idx_nodes = {}
    idx_node = 0
    dico_index = {}
    index = 0
    latscale = GEO.m_to_lat
    lonscale = latscale / cos(lat_anchor * pi / 180)
    f = open(objfile_name, "r")
    for line in f.readlines():
        if line[0:2] == "VT":
            (xo, yo, zo) = [float(s) for s in line.split()[1:4]]
            Xo = xo * cos(heading_anchor * pi / 180) - zo * sin(
                heading_anchor * pi / 180
            )
            Zo = xo * sin(heading_anchor * pi / 180) + zo * cos(
                heading_anchor * pi / 180
            )
            y = numpy.round(lat_anchor - latscale * float(Zo) - tile.lat, 7)
            x = numpy.round(lon_anchor + lonscale * float(Xo) - tile.lon, 7)
            z = yo + alt_anchor
            dico_idx_nodes[idx_node] = vector_map.insert_node(x, y, z)
            idx_node += 1
        elif line[0:3] == "IDX":
            dico_index[index] = [int(x) for x in line.split()[1:]]
            index += 1
        elif line[0:4] == "TRIS":
            (offset, count) = [int(x) for x in line.split()[1:3]]
            list = []
            count_tmp = 0
            try:
                polist = []
                while count_tmp < count:
                    list += dico_index[offset]
                    count_tmp += len(dico_index[offset])
                    offset += 1
                for j in range(count // 3):
                    (a, b, c) = [
                        dico_idx_nodes[x] for x in list[3 * j : 3 * j + 3]
                    ]
                    if a == b or a == c or b == c:
                        continue
                    for (initp, endp) in ((a, b), (b, c), (c, a)):
                        vector_map.insert_edge(
                            initp,
                            endp,
                            vector_map.dico_attributes["INTERP_ALT"],
                            check=True,
                        )
                    seed = (
                        numpy.array(vector_map.nodes_dico[a])
                        + numpy.array(vector_map.nodes_dico[b])
                        + numpy.array(vector_map.nodes_dico[c])
                    ) / 3
                    if "INTERP_ALT" in vector_map.seeds:
                        vector_map.seeds["INTERP_ALT"].append(seed)
                    else:
                        vector_map.seeds["INTERP_ALT"] = [seed]
                    polist.append(
                        geometry.Polygon(
                            [
                                vector_map.nodes_dico[a],
                                vector_map.nodes_dico[b],
                                vector_map.nodes_dico[c],
                                vector_map.nodes_dico[a],
                            ]
                        )
                    )
                multipol = VECT.ensure_MultiPolygon(ops.unary_union(polist))
            except:
                pass
    f.close()
    return multipol
