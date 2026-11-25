# Parity test bed - environment facts (recon 2026-11-25)

Read-only recon for the Unity-truth parity harness (nothing launched or built). Plan: `mem:parity_harness/plan`.
Related: `mem:transform_truth/transform_truth_plan`, `mem:transform_truth/working_documentation`.

## Source of truth (Unity)
- Project: `D:\OffLocalDev\dellagolayover`, Unity **2021.3.14f1**, URP 12.1.8. Git repo on Bitbucket with pending changes: never commit there.
- Editor installed: `C:\Program Files\Unity\Hub\Editor\2021.3.14f1`. License file present (`C:\ProgramData\Unity\Unity_lic.ulf`). `Library/` imported (last opened 2026-05-25), script assemblies compiled. Batchmode (`-batchmode -executeMethod`) is feasible on paper, NOT yet run.
- Pack: `Assets/OfficeAndPoliceStation` (1.8 GB): 232 FBX (12 dedicated `_COL` in `Colliders/`), 222 prefabs, 66 materials.
  - `Scenes/Showcase.unity` = asset gallery: 217 PrefabInstances over 216 distinct prefabs, 0 scale overrides.
  - `Scenes/OfficePack_Example.unity` = real interior: 1507 PrefabInstances, 192 distinct prefabs, 108 lights, 314 scale overrides (none negative).
  - Prefab components: 402 BoxCollider, 263 MeshFilter/MeshRenderer, 101 nested PrefabInstance (20 prefabs nest), 21 MeshCollider, 6 Animator.
  - No negative scale anywhere in the pack; 6 non-unit `m_LocalScale` lines in prefabs.
  - ALL 232 FBX `.meta` share one import config: `globalScale 1`, `useFileScale 1`, `useFileUnits 1`, `bakeAxisConversion 0`, `preserveHierarchy 0`, `sortHierarchyByName 1`. So per-asset variety comes from FBX content (UpAxis, node Lcl transforms), not from import settings.

## Destination (O3DE)
- Project: `D:\OffLocalDev\xxxxxDelete\ConverterTest` (blank, `Levels/DefaultLevel` only). O3DE MCP at `http://127.0.0.1:9078/mcp` (config profile, Ninja Multi-Config, MSVC, runTarget Editor).
- Engine: `GS_Play_Engine` **2.9.0**, installed SDK at `C:\Users\gaian\.o3de\Engines\GS_Play_Engine` (built 2026-11-15). `Editor.exe`, `AssetProcessor.exe`, `AssetProcessorBatch.exe` in `bin\Windows\profile\Default`. An older 2.7.0 is at `D:\GS_Sys\Engines\GS_Play_Engine`.
- Gems: Atom, PhysX5, EditorPythonBindings, PrimitiveAssets, DebugDraw, WhiteBox (no GS_Play gems). Project gem `ConverterTest.dll` is built; no GameLauncher exe.
- No `Cache/` yet: the Asset Processor has never run on it, so the first launch is a full cook.
- Transform 2 is in the SDK (`Transform2Bus.h`, `Transform2Math.h`, `Transform2Component.h`). Editor source: `D:\OffLocalDev\o3de_sourcedev` branch `Transform2-2026` (not the checked-out branch; read with `git show Transform2-2026:<path>`). `EditorTransform` fields: `Translate`, `Rotate`, `UniformScale`, `AuthoredScale` (Vector3, signed), `DeployExtended`. Design notes: `D:\OffLocalDev\CIPipelineTest\.serena\memories\transform2\`.
- `BoundsRequestBus` (`GetWorldBounds`, `GetLocalBounds`) is reflected to the behavior context, so Editor Python can read mesh bounds.

## Converter state relevant to a harness
- Headless entry since 2026-11-25: `converter_cli.py` (`truth`, `run`, `describe`), over `stage_runner.py`, which the GUI tabs call too.
- Does not emit Transform 2: non-uniform scale goes out as `EditorNonUniformScaleComponent` (`targets/o3de/prefab_writer.py`, `platforms/unity/scene_converter.py`). That is intended (the person, 2026-11-25): Transform 2 is only for negative scale.
- Python 3.9.13 has Pillow, PyYAML, UnityPy, PySide6 and `numpy`; `scipy` is not installed.
- Existing hand-made project for this pack: `D:\OffLocalDev\Unity to Converter Projects\Police Office.u2oproj.json` (outputs to `D:/OffLocalDev/ProjectSwitch`, not ConverterTest).

## Measured on this machine (2026-11-25)
- Unity 2021.3.14f1 opens the full project headless in 16 to 30 s. Unity Hub does not need to run.
- First Asset Processor cook of ConverterTest: 4064 assets, about 25 minutes. Unchanged cook: 45 to 50 s.
- Probe of the baked level in the Editor: about 45 s. A whole parity cycle: about 200 s.
- `numpy` 2.0.2 was installed into the Python 3.9 interpreter for the harness.
- The index of the converter repo holds LF; several working copies carry CRLF (`core.autocrlf` false).

## Reference harness
- `D:\OffLocalDev\gs_play\Tools\PerformerSmoke`: launches `Editor.exe --project-path <p> --autotest_mode --runpython <session.py> --runpythonargs <run_dir>` (run dir must have no spaces), screenshots through `azlmbr.atom.FrameCaptureRequestBus CaptureScreenshot`, contact sheet with Pillow, baked levels with a recipe hash, kills a hung Editor.
