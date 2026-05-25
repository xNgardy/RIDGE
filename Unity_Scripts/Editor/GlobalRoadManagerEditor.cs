using UnityEngine;
using UnityEditor; 

[CustomEditor(typeof(GlobalRoadManager))]
public class GlobalRoadManagerEditor : Editor
{
    public override void OnInspectorGUI()
    {
        // Standart değişkenleri (Terrain, Materyaller vs.) göster
        DrawDefaultInspector();

        GlobalRoadManager manager = (GlobalRoadManager)target;

        GUILayout.Space(20); 

       
        GUI.backgroundColor = Color.green;
        if (GUILayout.Button("Build Roads", GUILayout.Height(40)))
        {
            manager.BuildAllRoads();
        }

        GUILayout.Space(10);

        GUI.backgroundColor = new Color(1f, 0.5f, 0.5f);
        if (GUILayout.Button("Delete Roads", GUILayout.Height(30)))
        {
            // Yanlışlıkla basmaya karşı 
            if (EditorUtility.DisplayDialog("Delete the roads?",
                "Are you sure you want to delete ALL the roads created on the map?",
                "Yes, DELETE", "Cancel"))
            {
                manager.DeleteAllRoads();
            }
        }
    }
}
