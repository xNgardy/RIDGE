using UnityEngine;

[ExecuteAlways]
public class RandomBuildingSurfaceMaterialAssigner : MonoBehaviour
{
    [Header("Building Search")]
    [SerializeField] private Transform searchRoot;
    [SerializeField] private string buildingNamePrefix = "Building_";
    [SerializeField] private bool includeInactiveBuildings = true;

    [Header("Wall Materials")]
    [SerializeField] private Material[] wallMaterials;
    [SerializeField] private float wallTextureMetersPerTile = 8f;

    [Header("Roof Materials")]
    [SerializeField] private Material[] roofMaterials;
    [SerializeField] private float roofTextureMetersPerTile = 10f;

    [Header("Random")]
    [SerializeField] private bool useDeterministicMaterials = true;
    [SerializeField] private int materialSeed = 12345;

    [Header("Options")]
    [SerializeField] private bool applyOnStart = false;

    private const int WallSubMesh = 0;
    private const int RoofSubMesh = 1;

    private void Start()
    {
        if (Application.isPlaying && applyOnStart)
        {
            ApplyRandomSurfaceMaterials();
        }
    }

    [ContextMenu("Apply Random Building Surface Materials")]
    public void ApplyRandomSurfaceMaterials()
    {
        if (wallMaterials == null || wallMaterials.Length == 0)
        {
            Debug.LogWarning("RandomBuildingSurfaceMaterialAssigner: Please assign at least one wall material.");
            return;
        }

        if (roofMaterials == null || roofMaterials.Length == 0)
        {
            Debug.LogWarning("RandomBuildingSurfaceMaterialAssigner: Please assign at least one roof material.");
            return;
        }

        Transform root = searchRoot != null ? searchRoot : transform;
        MeshRenderer[] renderers = root.GetComponentsInChildren<MeshRenderer>(includeInactiveBuildings);
        int assignedCount = 0;

        foreach (MeshRenderer renderer in renderers)
        {
            GameObject buildingObject = renderer.gameObject;
            if (!IsBuilding(buildingObject))
            {
                continue;
            }

            MeshFilter meshFilter = buildingObject.GetComponent<MeshFilter>();
            if (meshFilter == null)
            {
                continue;
            }

            meshFilter.sharedMesh = CreateBuildingMesh(buildingObject.transform.localScale);
            renderer.sharedMaterials = new[]
            {
                GetMaterialForBuilding(buildingObject, wallMaterials, 0),
                GetMaterialForBuilding(buildingObject, roofMaterials, 1)
            };

            assignedCount++;
        }

        Debug.Log($"RandomBuildingSurfaceMaterialAssigner: Assigned wall and roof materials to {assignedCount} buildings.");
    }

    private bool IsBuilding(GameObject buildingObject)
    {
        return string.IsNullOrEmpty(buildingNamePrefix) || buildingObject.name.StartsWith(buildingNamePrefix);
    }

    private Material GetMaterialForBuilding(GameObject buildingObject, Material[] materials, int salt)
    {
        int materialIndex = useDeterministicMaterials
            ? GetDeterministicMaterialIndex(buildingObject, materials.Length, salt)
            : Random.Range(0, materials.Length);

        return materials[materialIndex];
    }

    private int GetDeterministicMaterialIndex(GameObject buildingObject, int materialCount, int salt)
    {
        unchecked
        {
            int hash = 17;
            hash = hash * 31 + materialSeed;
            hash = hash * 31 + salt;
            hash = hash * 31 + buildingObject.name.GetHashCode();
            hash = hash * 31 + Mathf.RoundToInt(buildingObject.transform.position.x * 10f);
            hash = hash * 31 + Mathf.RoundToInt(buildingObject.transform.position.z * 10f);

            return (hash & 0x7fffffff) % materialCount;
        }
    }

    private Mesh CreateBuildingMesh(Vector3 buildingScale)
    {
        float width = Mathf.Max(0.01f, Mathf.Abs(buildingScale.x));
        float height = Mathf.Max(0.01f, Mathf.Abs(buildingScale.y));
        float depth = Mathf.Max(0.01f, Mathf.Abs(buildingScale.z));

        float wallUWidth = width / Mathf.Max(0.01f, wallTextureMetersPerTile);
        float wallUDepth = depth / Mathf.Max(0.01f, wallTextureMetersPerTile);
        float wallV = height / Mathf.Max(0.01f, wallTextureMetersPerTile);
        float roofU = width / Mathf.Max(0.01f, roofTextureMetersPerTile);
        float roofV = depth / Mathf.Max(0.01f, roofTextureMetersPerTile);

        Vector3[] vertices =
        {
            // Front
            new(-0.5f, -0.5f, -0.5f), new(0.5f, -0.5f, -0.5f), new(0.5f, 0.5f, -0.5f), new(-0.5f, 0.5f, -0.5f),
            // Back
            new(0.5f, -0.5f, 0.5f), new(-0.5f, -0.5f, 0.5f), new(-0.5f, 0.5f, 0.5f), new(0.5f, 0.5f, 0.5f),
            // Left
            new(-0.5f, -0.5f, 0.5f), new(-0.5f, -0.5f, -0.5f), new(-0.5f, 0.5f, -0.5f), new(-0.5f, 0.5f, 0.5f),
            // Right
            new(0.5f, -0.5f, -0.5f), new(0.5f, -0.5f, 0.5f), new(0.5f, 0.5f, 0.5f), new(0.5f, 0.5f, -0.5f),
            // Roof
            new(-0.5f, 0.5f, -0.5f), new(0.5f, 0.5f, -0.5f), new(0.5f, 0.5f, 0.5f), new(-0.5f, 0.5f, 0.5f),
            // Bottom
            new(-0.5f, -0.5f, 0.5f), new(0.5f, -0.5f, 0.5f), new(0.5f, -0.5f, -0.5f), new(-0.5f, -0.5f, -0.5f)
        };

        Vector2[] uvs =
        {
            new(0f, 0f), new(wallUWidth, 0f), new(wallUWidth, wallV), new(0f, wallV),
            new(0f, 0f), new(wallUWidth, 0f), new(wallUWidth, wallV), new(0f, wallV),
            new(0f, 0f), new(wallUDepth, 0f), new(wallUDepth, wallV), new(0f, wallV),
            new(0f, 0f), new(wallUDepth, 0f), new(wallUDepth, wallV), new(0f, wallV),
            new(0f, 0f), new(roofU, 0f), new(roofU, roofV), new(0f, roofV),
            new(0f, 0f), new(roofU, 0f), new(roofU, roofV), new(0f, roofV)
        };

        int[] wallTriangles =
        {
            0, 2, 1, 0, 3, 2,
            4, 6, 5, 4, 7, 6,
            8, 10, 9, 8, 11, 10,
            12, 14, 13, 12, 15, 14,
            20, 22, 21, 20, 23, 22
        };

        int[] roofTriangles =
        {
            16, 18, 17, 16, 19, 18
        };

        Mesh mesh = new()
        {
            name = "Building_Surface_Mesh",
            vertices = vertices,
            uv = uvs,
            subMeshCount = 2
        };

        mesh.SetTriangles(wallTriangles, WallSubMesh);
        mesh.SetTriangles(roofTriangles, RoofSubMesh);
        mesh.RecalculateNormals();
        mesh.RecalculateBounds();

        return mesh;
    }
}
