using UnityEngine;
using UnityEditor;

[CustomEditor(typeof(TerrainMaterialPainter))]
public class TerrainMaterialPainterEditor : Editor
{
    public override void OnInspectorGUI()
    {
        DrawDefaultInspector();
        
        TerrainMaterialPainter painter = (TerrainMaterialPainter)target;
        
        EditorGUILayout.Space(10);
        EditorGUILayout.BeginVertical(EditorStyles.helpBox);
        EditorGUILayout.LabelField("Controls", EditorStyles.boldLabel);
        EditorGUILayout.Space(5);
        
        EditorGUILayout.BeginHorizontal();
        
        // Yeşil Buton
        GUI.backgroundColor = new Color(0.4f, 0.8f, 0.4f); 
        if (GUILayout.Button("Apply Material Masks", GUILayout.Height(30)))
        {
            painter.ApplyMaterialMasks();
            SceneView.RepaintAll();
        }
        
        // Mavi Buton
        GUI.backgroundColor = new Color(0.4f, 0.6f, 0.9f); 
        if (GUILayout.Button("Revert to Satellite", GUILayout.Height(30)))
        {
            painter.RevertToSatelliteImage();
            SceneView.RepaintAll();
        }
        
        GUI.backgroundColor = Color.white;
        EditorGUILayout.EndHorizontal();
        EditorGUILayout.EndVertical();
    }
}
