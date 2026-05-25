using UnityEditor;
using UnityEngine;

[CustomEditor(typeof(AdvancedTerrainMaterialPainter))]
public class AdvancedTerrainMaterialPainterEditor : Editor
{
    public override void OnInspectorGUI()
    {
        DrawDefaultInspector();

        AdvancedTerrainMaterialPainter painter = (AdvancedTerrainMaterialPainter)target;

        EditorGUILayout.Space(10);
        EditorGUILayout.BeginVertical(EditorStyles.helpBox);
        EditorGUILayout.LabelField("Controls", EditorStyles.boldLabel);
        EditorGUILayout.Space(5);

        EditorGUILayout.BeginHorizontal();

        GUI.backgroundColor = new Color(0.95f, 0.8f, 0.35f);
        if (GUILayout.Button("Load Islahiye Preset", GUILayout.Height(30)))
        {
            Undo.RecordObject(painter, "Load Islahiye Preset");
            painter.LoadIslahiyePreset();
            EditorUtility.SetDirty(painter);
        }

        GUI.backgroundColor = new Color(0.4f, 0.8f, 0.4f);
        if (GUILayout.Button("Apply Advanced Material Masks", GUILayout.Height(30)))
        {
            painter.ApplyMaterialMasks();
            SceneView.RepaintAll();
        }

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
