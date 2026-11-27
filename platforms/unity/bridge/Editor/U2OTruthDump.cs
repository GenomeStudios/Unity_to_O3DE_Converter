// =============================================================================
// U2O TRUTH DUMP
//
// Editor-only bridge script of the To-O3DE Project Converter.
//
// The converter copies this file into a Unity project (Assets/_U2OTruth/Editor)
// and starts Unity headless on it:
//
//   Unity -batchmode -projectPath <project>
//         -executeMethod U2OTruth.TruthDump.Run -u2oRequest <request.json>
//         -logFile <log> -quit
//
// It writes what Unity itself holds after import: every object of every prefab,
// model and scene with its transforms, meshes, materials and colliders, and the
// vertices of every mesh. That is the truth the converter's output is compared
// with. Nothing in the project is changed: no asset and no scene is saved.
//
// Output, under the request's outDir:
//   done.json            status, counts, warnings, errors
//   truth.json           catalog of everything written
//   prefabs/<guid>.json  one hierarchy per prefab
//   models/<guid>.json   one hierarchy per model file (FBX ...), as imported
//   scenes/<guid>.json   one hierarchy per scene
//   meshes.json          one record per mesh
//   meshes/<key>.pos     float32 x,y,z per vertex, little-endian
//   meshes/<key>.idx     int32 per index, little-endian, sub-meshes in order
//
// All values are Unity's own: metres, Y up, left-handed. Nothing is converted.
// =============================================================================

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace U2OTruth
{
    // =========================================================================
    // RECORDS
    // Plain serializable classes, written with JsonUtility. An optional part
    // carries a "has..." flag, because JsonUtility writes no nulls.
    // =========================================================================

    [Serializable]
    public class Request
    {
        public string mode = "dump";            // "check": start, count, leave. "dump": write everything.
        public string scope = "";               // asset folder, e.g. Assets/OfficeAndPoliceStation
        public string outDir = "";              // absolute folder for the output
        public string[] scenes = new string[0]; // asset paths of scenes to dump
        public string only = "";                // wildcard on asset file names; empty = everything
    }

    // Where an object comes from. The first link of an identity chain is the
    // object itself; each further link is the object it was instanced from.
    [Serializable]
    public class SourceRef
    {
        public string guid = "";            // asset (or scene) the object is stored in
        public string fileId = "";          // its local id in that file
        public string prefabId = "";        // scene objects only: id of the prefab instance they belong to
        public string instanceFileId = "";  // id of the PrefabInstance object that brought it into that file
        public string assetPath = "";
    }

    [Serializable]
    public class AssetRef
    {
        public string guid = "";
        public string fileId = "";
        public string name = "";
        public string assetPath = "";
    }

    [Serializable]
    public class ColliderRecord
    {
        public string type = "";            // Box, Sphere, Capsule, Mesh, CharacterController, or the class name
        public string fileId = "";
        public bool enabled;
        public bool isTrigger;
        public float[] center = new float[3];
        public float[] size = new float[3]; // Box
        public float radius;                // Sphere, Capsule, CharacterController
        public float height;                // Capsule, CharacterController
        public int direction;               // Capsule: 0 = X, 1 = Y, 2 = Z
        public bool convex;                 // Mesh
        public bool hasMesh;                // Mesh
        public AssetRef mesh = new AssetRef();
        public string physicMaterial = "";
    }

    [Serializable]
    public class RigidbodyRecord
    {
        public float mass;
        public float drag;
        public float angularDrag;
        public bool useGravity;
        public bool isKinematic;
        public int constraints;
    }

    [Serializable]
    public class LodRecord
    {
        public float screenHeight;
        public int[] rendererObjects = new int[0];  // object indices of this level's renderers
    }

    [Serializable]
    public class ObjectRecord
    {
        public int index;
        public int parent = -1;
        public string name = "";
        public string path = "";
        public bool activeSelf;
        public int layer;
        public string tag = "";
        public bool isStatic;

        public List<SourceRef> identity = new List<SourceRef>();
        public string transformFileId = "";
        public bool isInstanceRoot;
        public string instanceSourcePath = "";
        public string instanceSourceGuid = "";

        public float[] localPosition = new float[3];
        public float[] localRotation = new float[4];    // x, y, z, w
        public float[] localScale = new float[3];
        public float[] matrix = new float[12];          // rows of the 3x4 from the hierarchy's roots down

        public bool hasMesh;
        public bool skinned;
        public AssetRef mesh = new AssetRef();
        public bool hasRenderer;
        public bool rendererEnabled;
        public List<AssetRef> materials = new List<AssetRef>();

        public List<ColliderRecord> colliders = new List<ColliderRecord>();
        public bool hasRigidbody;
        public RigidbodyRecord rigidbody = new RigidbodyRecord();
        public List<LodRecord> lods = new List<LodRecord>();
        public List<string> components = new List<string>();
    }

    [Serializable]
    public class ImporterRecord
    {
        public float globalScale;
        public bool useFileScale;
        public float fileScale;
        public bool useFileUnits;
        public bool bakeAxisConversion;
        public bool preserveHierarchy;
        public bool sortHierarchyByName;
        public bool isReadable;
        public bool weldVertices;
        public bool optimizeMeshVertices;
        public bool optimizeMeshPolygons;
        public string meshCompression = "";
        public bool addCollider;
        public bool keepQuads;
    }

    // One prefab, one model or one scene.
    [Serializable]
    public class HierarchyRecord
    {
        public string kind = "";        // prefab, model, scene
        public string guid = "";
        public string assetPath = "";
        public string name = "";
        public string prefabType = "";  // Regular, Variant, Model; empty for a scene
        public bool hasImporter;
        public ImporterRecord importer = new ImporterRecord();
        public List<ObjectRecord> objects = new List<ObjectRecord>();
    }

    [Serializable]
    public class SubMeshRecord
    {
        public int indexStart;      // position in the .idx file
        public int indexCount;
        public string topology = "";
    }

    [Serializable]
    public class MeshRecord
    {
        public string key = "";     // <guid>_<fileId>, the name of its .pos and .idx files
        public string guid = "";
        public string fileId = "";
        public string name = "";
        public string assetPath = "";
        public bool readable;
        public int vertexCount;
        public int indexCount;
        public float[] boundsCenter = new float[3];
        public float[] boundsSize = new float[3];
        public List<SubMeshRecord> subMeshes = new List<SubMeshRecord>();
    }

    [Serializable]
    public class MeshIndex
    {
        public List<MeshRecord> meshes = new List<MeshRecord>();
    }

    [Serializable]
    public class CatalogEntry
    {
        public string guid = "";
        public string assetPath = "";
        public string file = "";
        public int objects;
    }

    [Serializable]
    public class Catalog
    {
        public string unityVersion = "";
        public string projectPath = "";
        public string scope = "";
        public string only = "";
        public List<CatalogEntry> prefabs = new List<CatalogEntry>();
        public List<CatalogEntry> models = new List<CatalogEntry>();
        public List<CatalogEntry> scenes = new List<CatalogEntry>();
        public int meshes;
    }

    [Serializable]
    public class Done
    {
        public string status = "failed";    // ok, failed
        public string mode = "";
        public string unityVersion = "";
        public string projectPath = "";
        public int prefabs;
        public int models;
        public int scenes;
        public int objects;
        public int meshes;
        public int vertices;
        public int matrixMismatches;        // objects whose composed matrix differs from Unity's own
        public float seconds;
        public List<string> warnings = new List<string>();
        public List<string> errors = new List<string>();
    }

    // =========================================================================
    // TRUTH DUMP
    // =========================================================================

    public static class TruthDump
    {
        const string LogPrefix = "[U2OTruth] ";
        const string RequestArgument = "-u2oRequest";

        // State of one run.
        static Request s_request;
        static Done s_done;
        static Dictionary<string, MeshRecord> s_meshes;

        // ---------------------------------------------------------------------
        // ENTRY POINT
        // ---------------------------------------------------------------------

        public static void Run()
        {
            var watch = System.Diagnostics.Stopwatch.StartNew();
            s_done = new Done();
            s_meshes = new Dictionary<string, MeshRecord>();
            s_request = null;

            try
            {
                s_request = ReadRequest();
                s_done.mode = s_request.mode;
                s_done.unityVersion = Application.unityVersion;
                s_done.projectPath = Path.GetDirectoryName(Application.dataPath).Replace('\\', '/');
                Directory.CreateDirectory(s_request.outDir);

                var prefabs = new List<string>();
                var models = new List<string>();
                CollectAssets(s_request.scope, s_request.only, prefabs, models);
                Log("found " + prefabs.Count + " prefab(s) and " + models.Count + " model(s) in " + s_request.scope);

                if (s_request.mode == "check")
                {
                    s_done.prefabs = prefabs.Count;
                    s_done.models = models.Count;
                }
                else
                {
                    DumpEverything(prefabs, models);
                }
                s_done.status = s_done.errors.Count == 0 ? "ok" : "failed";
            }
            catch (Exception exception)
            {
                s_done.errors.Add(exception.ToString());
                s_done.status = "failed";
                Debug.LogError(LogPrefix + exception);
            }

            s_done.seconds = (float)watch.Elapsed.TotalSeconds;
            WriteDone();
            EditorApplication.Exit(s_done.status == "ok" ? 0 : 1);
        }

        static Request ReadRequest()
        {
            string[] arguments = Environment.GetCommandLineArgs();
            int at = Array.IndexOf(arguments, RequestArgument);
            if (at < 0 || at + 1 >= arguments.Length)
            {
                throw new ArgumentException("missing " + RequestArgument + " <request.json> on the command line");
            }
            var request = JsonUtility.FromJson<Request>(File.ReadAllText(arguments[at + 1]));
            if (string.IsNullOrEmpty(request.outDir))
            {
                throw new ArgumentException("the request names no outDir");
            }
            if (string.IsNullOrEmpty(request.scope) || !AssetDatabase.IsValidFolder(request.scope))
            {
                throw new ArgumentException("the request's scope is not an asset folder: '" + request.scope + "'");
            }
            return request;
        }

        static void WriteDone()
        {
            if (s_request == null || string.IsNullOrEmpty(s_request.outDir))
            {
                Debug.LogError(LogPrefix + "no output folder is known, done.json was not written");
                return;
            }
            Directory.CreateDirectory(s_request.outDir);
            File.WriteAllText(Path.Combine(s_request.outDir, "done.json"), JsonUtility.ToJson(s_done, true));
            Log("done: " + s_done.status + " in " + s_done.seconds.ToString("0.0", CultureInfo.InvariantCulture) + " s");
        }

        static void Log(string message)
        {
            Debug.Log(LogPrefix + message);
        }

        // ---------------------------------------------------------------------
        // WHAT TO DUMP
        // ---------------------------------------------------------------------

        static void CollectAssets(string scope, string only, List<string> prefabs, List<string> models)
        {
            var seen = new HashSet<string>();
            string[] folders = { scope };
            foreach (string filter in new[] { "t:GameObject", "t:Prefab", "t:Model" })
            {
                foreach (string guid in AssetDatabase.FindAssets(filter, folders))
                {
                    string path = AssetDatabase.GUIDToAssetPath(guid);
                    if (!seen.Add(path) || !Matches(path, only))
                    {
                        continue;
                    }
                    if (path.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
                    {
                        prefabs.Add(path);
                    }
                    else if (AssetImporter.GetAtPath(path) is ModelImporter)
                    {
                        models.Add(path);
                    }
                }
            }
            prefabs.Sort(StringComparer.Ordinal);
            models.Sort(StringComparer.Ordinal);
        }

        // "only" is a wildcard (* and ?) on the file name without its extension.
        static bool Matches(string assetPath, string only)
        {
            if (string.IsNullOrEmpty(only))
            {
                return true;
            }
            string pattern = "^" + Regex.Escape(only).Replace("\\*", ".*").Replace("\\?", ".") + "$";
            return Regex.IsMatch(Path.GetFileNameWithoutExtension(assetPath), pattern, RegexOptions.IgnoreCase);
        }

        static void DumpEverything(List<string> prefabs, List<string> models)
        {
            var catalog = new Catalog();
            catalog.unityVersion = s_done.unityVersion;
            catalog.projectPath = s_done.projectPath;
            catalog.scope = s_request.scope;
            catalog.only = s_request.only;

            foreach (string path in prefabs)
            {
                catalog.prefabs.Add(DumpAsset("prefab", path, "prefabs"));
            }
            s_done.prefabs = catalog.prefabs.Count;
            Log("prefabs written: " + s_done.prefabs);

            foreach (string path in models)
            {
                catalog.models.Add(DumpAsset("model", path, "models"));
            }
            s_done.models = catalog.models.Count;
            Log("models written: " + s_done.models);

            foreach (string path in s_request.scenes)
            {
                catalog.scenes.Add(DumpScene(path));
            }
            s_done.scenes = catalog.scenes.Count;
            Log("scenes written: " + s_done.scenes);

            WriteMeshIndex();
            catalog.meshes = s_done.meshes;
            File.WriteAllText(Path.Combine(s_request.outDir, "truth.json"), JsonUtility.ToJson(catalog, true));
        }

        // ---------------------------------------------------------------------
        // PREFABS AND MODELS
        // Read straight from the asset: nothing is instanced into a scene.
        // ---------------------------------------------------------------------

        static CatalogEntry DumpAsset(string kind, string assetPath, string folder)
        {
            var root = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
            var record = new HierarchyRecord();
            record.kind = kind;
            record.guid = AssetDatabase.AssetPathToGUID(assetPath);
            record.assetPath = assetPath;
            record.name = Path.GetFileNameWithoutExtension(assetPath);

            if (root == null)
            {
                s_done.errors.Add("could not load " + assetPath);
                return WriteHierarchy(record, folder);
            }

            record.prefabType = PrefabUtility.GetPrefabAssetType(root).ToString();
            var importer = AssetImporter.GetAtPath(assetPath) as ModelImporter;
            if (importer != null)
            {
                record.hasImporter = true;
                record.importer = DumpImporter(importer);
                // Every mesh of the file, also those no object of its hierarchy shows.
                foreach (UnityEngine.Object part in AssetDatabase.LoadAllAssetsAtPath(assetPath))
                {
                    var mesh = part as Mesh;
                    if (mesh != null)
                    {
                        RegisterMesh(mesh);
                    }
                }
            }

            DumpHierarchy(record, new[] { root });
            return WriteHierarchy(record, folder);
        }

        static ImporterRecord DumpImporter(ModelImporter importer)
        {
            var record = new ImporterRecord();
            record.globalScale = importer.globalScale;
            record.useFileScale = importer.useFileScale;
            record.fileScale = importer.fileScale;
            record.useFileUnits = importer.useFileUnits;
            record.bakeAxisConversion = importer.bakeAxisConversion;
            record.preserveHierarchy = importer.preserveHierarchy;
            record.sortHierarchyByName = importer.sortHierarchyByName;
            record.isReadable = importer.isReadable;
            record.weldVertices = importer.weldVertices;
            record.optimizeMeshVertices = importer.optimizeMeshVertices;
            record.optimizeMeshPolygons = importer.optimizeMeshPolygons;
            record.meshCompression = importer.meshCompression.ToString();
            record.addCollider = importer.addCollider;
            record.keepQuads = importer.keepQuads;
            return record;
        }

        // ---------------------------------------------------------------------
        // SCENES
        // Opened, read and left. Never saved.
        // ---------------------------------------------------------------------

        static CatalogEntry DumpScene(string assetPath)
        {
            var record = new HierarchyRecord();
            record.kind = "scene";
            record.guid = AssetDatabase.AssetPathToGUID(assetPath);
            record.assetPath = assetPath;
            record.name = Path.GetFileNameWithoutExtension(assetPath);

            if (string.IsNullOrEmpty(record.guid))
            {
                s_done.errors.Add("scene not found: " + assetPath);
                return WriteHierarchy(record, "scenes");
            }

            Scene scene = EditorSceneManager.OpenScene(assetPath, OpenSceneMode.Single);
            DumpHierarchy(record, scene.GetRootGameObjects());
            CatalogEntry entry = WriteHierarchy(record, "scenes");
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            return entry;
        }

        // ---------------------------------------------------------------------
        // HIERARCHY
        // ---------------------------------------------------------------------

        static void DumpHierarchy(HierarchyRecord record, IList<GameObject> roots)
        {
            var walked = new List<GameObject>();
            foreach (GameObject root in roots)
            {
                Walk(root.transform, -1, Matrix4x4.identity, "", record, walked);
            }
            FillLods(record, walked);
            s_done.objects += record.objects.Count;
        }

        static void Walk(Transform transform, int parentIndex, Matrix4x4 parentMatrix, string parentPath,
                         HierarchyRecord record, List<GameObject> walked)
        {
            // The matrix is composed from the stored local values, so it does not
            // depend on how Unity keeps the world state of an asset's objects.
            // Unity's own matrix is only used to check the composition.
            Matrix4x4 matrix = parentMatrix
                * Matrix4x4.TRS(transform.localPosition, transform.localRotation, transform.localScale);
            if (!Close(matrix, transform.localToWorldMatrix))
            {
                s_done.matrixMismatches++;
            }

            ObjectRecord item = DumpObject(transform.gameObject, record.objects.Count, parentIndex, parentPath, matrix);
            record.objects.Add(item);
            walked.Add(transform.gameObject);

            for (int child = 0; child < transform.childCount; child++)
            {
                Walk(transform.GetChild(child), item.index, matrix, item.path, record, walked);
            }
        }

        static bool Close(Matrix4x4 a, Matrix4x4 b)
        {
            for (int row = 0; row < 3; row++)
            {
                for (int column = 0; column < 4; column++)
                {
                    float limit = 1e-4f * (1f + Mathf.Abs(b[row, column]));
                    if (Mathf.Abs(a[row, column] - b[row, column]) > limit)
                    {
                        return false;
                    }
                }
            }
            return true;
        }

        // A LOD group names its renderers by object. Object indices are only
        // known once the whole hierarchy has been walked.
        static void FillLods(HierarchyRecord record, List<GameObject> walked)
        {
            var indexOf = new Dictionary<int, int>();
            for (int index = 0; index < walked.Count; index++)
            {
                indexOf[walked[index].GetInstanceID()] = index;
            }

            for (int index = 0; index < walked.Count; index++)
            {
                var group = walked[index].GetComponent<LODGroup>();
                if (group == null)
                {
                    continue;
                }
                foreach (LOD level in group.GetLODs())
                {
                    var lod = new LodRecord();
                    lod.screenHeight = level.screenRelativeTransitionHeight;
                    var objects = new List<int>();
                    foreach (Renderer renderer in level.renderers)
                    {
                        int found;
                        if (renderer != null && indexOf.TryGetValue(renderer.gameObject.GetInstanceID(), out found))
                        {
                            objects.Add(found);
                        }
                    }
                    lod.rendererObjects = objects.ToArray();
                    record.objects[index].lods.Add(lod);
                }
            }
        }

        static CatalogEntry WriteHierarchy(HierarchyRecord record, string folder)
        {
            string directory = Path.Combine(s_request.outDir, folder);
            Directory.CreateDirectory(directory);
            string file = folder + "/" + record.guid + ".json";
            File.WriteAllText(Path.Combine(s_request.outDir, file), JsonUtility.ToJson(record, true));

            var entry = new CatalogEntry();
            entry.guid = record.guid;
            entry.assetPath = record.assetPath;
            entry.file = file;
            entry.objects = record.objects.Count;
            return entry;
        }

        // ---------------------------------------------------------------------
        // ONE OBJECT
        // ---------------------------------------------------------------------

        static ObjectRecord DumpObject(GameObject gameObject, int index, int parentIndex, string parentPath,
                                       Matrix4x4 matrix)
        {
            Transform transform = gameObject.transform;
            var item = new ObjectRecord();
            item.index = index;
            item.parent = parentIndex;
            item.name = gameObject.name;
            item.path = string.IsNullOrEmpty(parentPath) ? gameObject.name : parentPath + "/" + gameObject.name;
            item.activeSelf = gameObject.activeSelf;
            item.layer = gameObject.layer;
            item.tag = gameObject.tag;
            item.isStatic = gameObject.isStatic;

            // Identity
            item.identity = IdentityChain(gameObject);
            item.transformFileId = Identify(transform).fileId;
            item.isInstanceRoot = PrefabUtility.IsAnyPrefabInstanceRoot(gameObject);
            if (PrefabUtility.IsPartOfPrefabInstance(gameObject))
            {
                item.instanceSourcePath = PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(gameObject);
                item.instanceSourceGuid = AssetDatabase.AssetPathToGUID(item.instanceSourcePath);
            }

            // Transform
            item.localPosition = ToArray(transform.localPosition);
            item.localRotation = ToArray(transform.localRotation);
            item.localScale = ToArray(transform.localScale);
            item.matrix = ToArray(matrix);

            // Mesh and materials
            var filter = gameObject.GetComponent<MeshFilter>();
            var skinned = gameObject.GetComponent<SkinnedMeshRenderer>();
            Mesh mesh = filter != null ? filter.sharedMesh : (skinned != null ? skinned.sharedMesh : null);
            if (mesh != null)
            {
                item.hasMesh = true;
                item.skinned = skinned != null && filter == null;
                item.mesh = RegisterMesh(mesh);
            }
            var renderer = gameObject.GetComponent<Renderer>();
            if (renderer != null)
            {
                item.hasRenderer = true;
                item.rendererEnabled = renderer.enabled;
                foreach (Material material in renderer.sharedMaterials)
                {
                    item.materials.Add(RefOf(material));
                }
            }

            // Physics
            foreach (Collider collider in gameObject.GetComponents<Collider>())
            {
                item.colliders.Add(DumpCollider(collider));
            }
            var body = gameObject.GetComponent<Rigidbody>();
            if (body != null)
            {
                item.hasRigidbody = true;
                item.rigidbody.mass = body.mass;
                item.rigidbody.drag = body.drag;
                item.rigidbody.angularDrag = body.angularDrag;
                item.rigidbody.useGravity = body.useGravity;
                item.rigidbody.isKinematic = body.isKinematic;
                item.rigidbody.constraints = (int)body.constraints;
            }

            // Every component by class name, for coverage
            foreach (Component component in gameObject.GetComponents<Component>())
            {
                item.components.Add(component == null ? "MissingScript" : component.GetType().Name);
            }
            return item;
        }

        static ColliderRecord DumpCollider(Collider collider)
        {
            var record = new ColliderRecord();
            record.fileId = Identify(collider).fileId;
            record.enabled = collider.enabled;
            record.isTrigger = collider.isTrigger;
            record.physicMaterial = collider.sharedMaterial != null ? collider.sharedMaterial.name : "";

            var box = collider as BoxCollider;
            var sphere = collider as SphereCollider;
            var capsule = collider as CapsuleCollider;
            var meshCollider = collider as MeshCollider;
            var character = collider as CharacterController;

            if (box != null)
            {
                record.type = "Box";
                record.center = ToArray(box.center);
                record.size = ToArray(box.size);
            }
            else if (sphere != null)
            {
                record.type = "Sphere";
                record.center = ToArray(sphere.center);
                record.radius = sphere.radius;
            }
            else if (capsule != null)
            {
                record.type = "Capsule";
                record.center = ToArray(capsule.center);
                record.radius = capsule.radius;
                record.height = capsule.height;
                record.direction = capsule.direction;
            }
            else if (meshCollider != null)
            {
                record.type = "Mesh";
                record.convex = meshCollider.convex;
                if (meshCollider.sharedMesh != null)
                {
                    record.hasMesh = true;
                    record.mesh = RegisterMesh(meshCollider.sharedMesh);
                }
            }
            else if (character != null)
            {
                record.type = "CharacterController";
                record.center = ToArray(character.center);
                record.radius = character.radius;
                record.height = character.height;
                record.direction = 1;
            }
            else
            {
                record.type = collider.GetType().Name;
            }
            return record;
        }

        // ---------------------------------------------------------------------
        // IDENTITY
        // ---------------------------------------------------------------------

        // The object, then the object it was instanced from, and so on down to
        // the asset that first defined it. The converter keys its entities by
        // these file ids, so the chain is what joins a converted entity to the
        // object it came from.
        static List<SourceRef> IdentityChain(UnityEngine.Object start)
        {
            var chain = new List<SourceRef>();
            UnityEngine.Object current = start;
            for (int depth = 0; current != null && depth < 16; depth++)
            {
                SourceRef link = Identify(current);
                UnityEngine.Object handle = PrefabUtility.GetPrefabInstanceHandle(current);
                if (handle != null)
                {
                    link.instanceFileId = Identify(handle).fileId;
                }
                chain.Add(link);
                current = PrefabUtility.GetCorrespondingObjectFromSource(current);
            }
            return chain;
        }

        // An object stored in an asset has a guid and a local file id. An object
        // of an open scene has a global object id instead, whose target id is
        // its local id in the scene file.
        static SourceRef Identify(UnityEngine.Object target)
        {
            var link = new SourceRef();
            if (target == null)
            {
                return link;
            }

            string guid;
            long localId;
            if (EditorUtility.IsPersistent(target)
                && AssetDatabase.TryGetGUIDAndLocalFileIdentifier(target, out guid, out localId))
            {
                link.guid = guid;
                link.fileId = localId.ToString(CultureInfo.InvariantCulture);
            }
            else
            {
                GlobalObjectId id = GlobalObjectId.GetGlobalObjectIdSlow(target);
                link.guid = id.assetGUID.ToString();
                link.fileId = id.targetObjectId.ToString(CultureInfo.InvariantCulture);
                link.prefabId = id.targetPrefabId.ToString(CultureInfo.InvariantCulture);
            }
            link.assetPath = AssetDatabase.GUIDToAssetPath(link.guid);
            return link;
        }

        static AssetRef RefOf(UnityEngine.Object asset)
        {
            var reference = new AssetRef();
            if (asset == null)
            {
                return reference;
            }
            SourceRef link = Identify(asset);
            reference.guid = link.guid;
            reference.fileId = link.fileId;
            reference.assetPath = link.assetPath;
            reference.name = asset.name;
            return reference;
        }

        // ---------------------------------------------------------------------
        // MESHES
        // Each mesh is written once, whatever number of objects use it, and
        // when it is first met: a mesh that lives in a scene is destroyed
        // when the scene is left.
        // ---------------------------------------------------------------------

        static AssetRef RegisterMesh(Mesh mesh)
        {
            AssetRef reference = RefOf(mesh);
            string key = reference.guid + "_" + reference.fileId;
            if (!s_meshes.ContainsKey(key))
            {
                string directory = Path.Combine(s_request.outDir, "meshes");
                Directory.CreateDirectory(directory);
                s_meshes[key] = WriteMesh(key, mesh, directory);
            }
            return reference;
        }

        static void WriteMeshIndex()
        {
            var keys = new List<string>(s_meshes.Keys);
            keys.Sort(StringComparer.Ordinal);

            var index = new MeshIndex();
            foreach (string key in keys)
            {
                index.meshes.Add(s_meshes[key]);
            }
            s_done.meshes = index.meshes.Count;
            File.WriteAllText(Path.Combine(s_request.outDir, "meshes.json"), JsonUtility.ToJson(index, true));
            Log("meshes written: " + s_done.meshes + " (" + s_done.vertices + " vertices)");
        }

        static MeshRecord WriteMesh(string key, Mesh mesh, string directory)
        {
            AssetRef reference = RefOf(mesh);
            var record = new MeshRecord();
            record.key = key;
            record.guid = reference.guid;
            record.fileId = reference.fileId;
            record.name = reference.name;
            record.assetPath = reference.assetPath;
            record.readable = mesh.isReadable;
            record.vertexCount = mesh.vertexCount;
            record.boundsCenter = ToArray(mesh.bounds.center);
            record.boundsSize = ToArray(mesh.bounds.size);

            Vector3[] positions = mesh.vertices;
            if (positions.Length != mesh.vertexCount)
            {
                s_done.warnings.Add("vertices of mesh '" + mesh.name + "' (" + reference.assetPath
                    + ") could not be read: enable Read/Write on its importer");
                return record;
            }

            using (var writer = new BinaryWriter(File.Create(Path.Combine(directory, key + ".pos"))))
            {
                foreach (Vector3 position in positions)
                {
                    writer.Write(position.x);
                    writer.Write(position.y);
                    writer.Write(position.z);
                }
            }

            using (var writer = new BinaryWriter(File.Create(Path.Combine(directory, key + ".idx"))))
            {
                for (int subMesh = 0; subMesh < mesh.subMeshCount; subMesh++)
                {
                    int[] indices = mesh.GetIndices(subMesh);
                    var part = new SubMeshRecord();
                    part.indexStart = record.indexCount;
                    part.indexCount = indices.Length;
                    part.topology = mesh.GetTopology(subMesh).ToString();
                    record.subMeshes.Add(part);
                    foreach (int vertex in indices)
                    {
                        writer.Write(vertex);
                    }
                    record.indexCount += indices.Length;
                }
            }

            s_done.vertices += positions.Length;
            return record;
        }

        // ---------------------------------------------------------------------
        // VALUES
        // ---------------------------------------------------------------------

        static float[] ToArray(Vector3 value)
        {
            return new[] { value.x, value.y, value.z };
        }

        static float[] ToArray(Quaternion value)
        {
            return new[] { value.x, value.y, value.z, value.w };
        }

        static float[] ToArray(Matrix4x4 value)
        {
            return new[]
            {
                value.m00, value.m01, value.m02, value.m03,
                value.m10, value.m11, value.m12, value.m13,
                value.m20, value.m21, value.m22, value.m23,
            };
        }
    }
}
