using UnityEngine;
using UnityEditor;

[CustomEditor(typeof(NDVITreePlacer))]
public class NDVITreePlacerEditor : Editor
{
    private bool treesVisible = true;

    public override void OnInspectorGUI()
    {
        DrawDefaultInspector();
        
        NDVITreePlacer placer = (NDVITreePlacer)target;
        
        EditorGUILayout.Space(10);
        
        EditorGUILayout.BeginVertical(EditorStyles.helpBox);
        EditorGUILayout.LabelField("Tree Placement Controls", EditorStyles.boldLabel);
        EditorGUILayout.Space(5);
        
        EditorGUILayout.BeginHorizontal();
        
        GUI.backgroundColor = new Color(0.4f, 0.8f, 0.4f);
        if (GUILayout.Button("Place Trees", GUILayout.Height(30)))
        {
            placer.PlaceAllTrees();
            EditorApplication.Beep();
            SceneView.RepaintAll();
        }
        
        GUI.backgroundColor = new Color(0.9f, 0.4f, 0.4f);
        if (GUILayout.Button("Clear Trees", GUILayout.Height(30)))
        {
            if (EditorUtility.DisplayDialog("Clear Trees", 
                "Are you sure you want to remove all trees?", 
                "Yes", "Cancel"))
            {
                placer.ClearAllTrees();
                SceneView.RepaintAll();
            }
        }
        
        GUI.backgroundColor = Color.white;
        EditorGUILayout.EndHorizontal();
        
        EditorGUILayout.Space(5);
        
        GUI.backgroundColor = treesVisible ? new Color(0.8f, 0.8f, 0.4f) : new Color(0.5f, 0.5f, 0.5f);
        string buttonLabel = treesVisible ? "Hide Terrain Trees" : "Show Terrain Trees";
        if (GUILayout.Button(buttonLabel, GUILayout.Height(25)))
        {
            treesVisible = !treesVisible;
            placer.SetTerrainTreesVisible(treesVisible);
            SceneView.RepaintAll();
        }
        GUI.backgroundColor = Color.white;
        
        EditorGUILayout.EndVertical();
        
        EditorGUILayout.Space(5);
        
        EditorGUILayout.HelpBox(
            "1. Run generate_tree_masks.py to create tree data\n" +
            "2. Copy tiles_trees folder to Resources\n" +
            "3. Assign tree prefabs\n" +
            "4. Click 'Place Trees'",
            MessageType.Info
        );
    }
}
