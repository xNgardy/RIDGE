# Intrinsic
- build_poly_file (function)
- include_sea (function)
- include_water (function)
- filter_large_lakes (function)


 ```
    Don't forget to remove custom directory functionality in inlcude_sea() and include_water()
 ```

# Extrinsic
- UI_Utils
    - is_working (field)
    - red_flag (field)
    - logprint (function)
    - vprint (function)
    - exit_message_and_bottom_line (function)
    - timings_and_bottom_line (function)
    - local_data_root (field) (set in Ortho4XP.py)

- Config_utils
    - Tile 
        - iterate (field)
        - build_dir (field)
        - lat (field)
        - lon (field)
        - mesh_zl (field)
        - dem (object?)
            - alt_vec (field?)
            - alt_dem
            


- Vector_Utils !!!!!!!!!!!!!!!!!
    - scalx (field)
    - Vector_Map (class)
        - dico_edges (field)
        - encode_MultiLineString (method)
        - seeds (field)
        - snap_to_grid (method)
        - write_node_file (method)
        - write_poly_file (method)
        - snap_to_grid (method)
        - encode_MultiPolygon (method)
    - cut_to_tile (function)
    - ensure_MultiLineString (function)
    - ensure_MultiPolygon (function)
    - coastline_to_MultiPolygon (function)
    - add_water_to_Vector_Map (function)
    - MultiPolygon_to_Indexed_Polygons (function)


- File_Names
    - short_latlon (function)
    - osm_dir (function)
    - input_node_file (function)
    - input_poly_file (function)
    - custom_coastline (function) ?????
    - custom_coastline_dir (function) ?????
    - custom_water (function) ?????
    - custom_water_dir (function) ?????

- Geo_Utils 
    - wgs84_to_orthogrid (function)
    - lat_to_m (field)
    - lon_to_m (function)


- OSM_Utils
    - OSM_layer (class)
        - update_dicosm (method)
        - write_to_file (method)
    - OSM_queries_to_OSM_layer (functoin) ????? (Not used in local mode)
    - OSM_to_MultiLineString (function)


- Local_Data
    - get_local_water_features (function)
