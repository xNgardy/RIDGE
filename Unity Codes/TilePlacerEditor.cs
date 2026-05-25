using UnityEngine;
using UnityEditor;

[CustomEditor(typeof(TilePlacer))]
public class TilePlacerEditor : Editor
{
    public override void OnInspectorGUI()
    {
        // Call the base class to ensure default inspector GUI is shown
        DrawDefaultInspector();

        TilePlacer placer = (TilePlacer)target;

        EditorGUILayout.Space();

        EditorGUILayout.BeginVertical();

        EditorGUILayout.BeginHorizontal();

        if (GUILayout.Button("Read Json"))
        {
            placer.ReadJson();
            EditorApplication.Beep();
        }

        if (GUILayout.Button("Change Setup"))
        {
            placer.PlaceTiles();
            EditorApplication.Beep();
        }

        if (GUILayout.Button("Read Building Json"))
        {
            placer.buildingPlacer.ReadJson();
            EditorApplication.Beep();
        }

        if (GUILayout.Button("Place Buildings"))
        {
            placer.buildingPlacer.PlaceBuildings();
            EditorApplication.Beep();
        }

        EditorGUILayout.EndHorizontal();

        if (GUILayout.Button("Delete Tiles"))
        {
            placer.DeleteTiles();
        }

        EditorGUILayout.EndVertical();
    }
}
