using UnityEngine;
using UnityEditor; // Bu kütüphane şart!

[CustomEditor(typeof(GlobalRoadManager))]
public class GlobalRoadManagerEditor : Editor
{
    public override void OnInspectorGUI()
    {
        // Standart değişkenleri (Terrain, Materyaller vs.) göster
        DrawDefaultInspector();

        GlobalRoadManager manager = (GlobalRoadManager)target;

        GUILayout.Space(20); // Biraz boşluk bırak

        // --- YEŞİL BUTON: İNŞA ET ---
        GUI.backgroundColor = Color.green;
        if (GUILayout.Button("🚧 Yolları İnşa Et 🚧", GUILayout.Height(40)))
        {
            manager.BuildAllRoads();
        }

        GUILayout.Space(10);

        // --- KIRMIZI BUTON: SİL ---
        GUI.backgroundColor = new Color(1f, 0.5f, 0.5f); // Açık kırmızı
        if (GUILayout.Button("🗑️ Tüm Yolları Sil", GUILayout.Height(30)))
        {
            // Yanlışlıkla basmaya karşı emin misin diye soralım
            if (EditorUtility.DisplayDialog("Yolları Sil?",
                "Haritadaki oluşturulmuş TÜM yolları silmek istediğine emin misin?",
                "Evet, Sil", "İptal"))
            {
                manager.DeleteAllRoads();
            }
        }
    }
}