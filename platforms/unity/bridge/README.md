# Unity bridge

Runs the Unity Editor headless on a Unity project and has it write the **truth dump**: what Unity itself holds
after import. The converter's output is compared with it (see `parity/`).

```
python converter_cli.py truth <project.u2oproj.json> --out <folder>
python converter_cli.py truth <project.u2oproj.json> --out <folder> --check
python converter_cli.py truth <project.u2oproj.json> --out <folder> --only "Desk_*" --fresh
```

The project file gives the scope (`scope_root`) and the scenes marked on the scene converter stage.

## What you need

| Requirement | Why | What you see without it |
|---|---|---|
| The Unity Editor of the project's own version (`ProjectSettings/ProjectVersion.txt`), installed and licensed | Another version would re-import the project, and its result would not be the project's truth | `Unity Editor <version> is not installed.` |
| The project closed in Unity | Unity opens a project once | `The project ... is open in Unity.` |
| Write access to the project's `Assets` folder | The bridge script is compiled by the project | `No write access to ...` |

The Editor is found in Unity Hub's install folders. To use another one, pass `--unity <executable>` or set
`U2O_UNITY_EDITOR`. Unity Hub does not have to be running.

`--check` starts Unity, compiles the script, counts the assets and leaves. Use it to try a machine.

## What it does to the Unity project

- Copies `Editor/U2OTruthDump.cs` and its assembly definition to `Assets/_U2OTruth/Editor/`.
- In a git repository, lists that folder and its `.meta` file in `.git/info/exclude`, the ignore file that is local
  to one clone, so the folder never shows in `git status`.
- Nothing else. The script saves no asset and no scene.

Unity itself may. Opening a project, it upgrades what an older version or an earlier render pipeline saved and
writes the files back (two materials of one pack, on a first run). The run compares the scope before and after
and names every file Unity changed, in its output and as the result's `changed_files`; they are left as Unity
wrote them. The dump is then filed under what the project looks like afterwards, so the next request finds it.

Nothing of Unity's ships with the converter. The script is the converter's own source and uses the public Editor
API. A dump holds data derived from the project's assets: keep it out of version control.

## The dump

Written to `<folder>/<fingerprint>/`. The fingerprint covers every file of the scope and scenes (path, size,
modification time), the script, the Editor version and the request, so a second run on unchanged files is answered
from the first (`--fresh` forces a new one). `<folder>/latest.json` names the newest dump.

| File | Content |
|---|---|
| `done.json` | status, counts, warnings, errors |
| `truth.json` | catalog: every prefab, model and scene written |
| `prefabs/<guid>.json` | one hierarchy per prefab |
| `models/<guid>.json` | one hierarchy per model file as imported, with its import settings |
| `scenes/<guid>.json` | one hierarchy per scene |
| `meshes.json` | one record per mesh |
| `meshes/<key>.pos`, `.idx` | vertex positions (float32 x, y, z) and indices (int32), little-endian |
| `unity_editor.log` | the Editor's own log of the run |

All values are Unity's: metres, Y up, left-handed. Nothing is converted.

Per object: name, parent, local position, rotation and scale; its 3x4 `matrix` composed from the stored local
values from the hierarchy's roots down (roots included); mesh and materials; colliders with their raw parameters;
rigid body; LOD levels; the class names of its components.

`identity` is a chain. Its first link is the object itself (the file it is stored in and its local id), each
further link the object it was instanced from, down to the asset that first defined it. `instanceFileId` is the
id of the `PrefabInstance` that brought it into that file. The converter keys its entities by these ids.

`matrixMismatches` in `done.json` counts objects whose composed matrix differs from Unity's own
`localToWorldMatrix`. It should be 0.
