# Parity harness

Measures how close the converter's output is to what Unity holds, element by element, and says what is wrong with
each element that is not.

Unity is the truth. A prefab is measured in Unity itself, converted, cooked, measured again in O3DE, and the two
measurements are compared in one frame.

```
python parity/parity.py cycle parity/configs/office.json
python parity/parity.py cycle parity/configs/office.json --set mesh_processor.defaults.auto_center=false
python parity/parity.py compare parity/configs/office.json --only "Desk_*"
```

Before a cycle: close the Unity project, the O3DE Editor and the Asset Processor. A cycle on the Office pack takes
a few minutes once the project's assets have been cooked the first time. A cycle never closes an Editor or an Asset
Processor it did not start: with one open on the project it stops and says so.

## Test beds

A bed is a config in `parity/configs/` and the conversion project it names. Several beds can share one O3DE project:

| Bed | Source | Converted into | Run folder |
|---|---|---|---|
| `office.json` | `Assets/OfficeAndPoliceStation` | `Assets/OfficePack`, level `Bench_Parity_Office` | `user/Parity` |
| `tirgames.json` | `Assets/TirgamesAssets` | `Assets/TirgamesPack`, level `Bench_Parity_Tirgames` | `user/Parity_Tirgames` |
| `nature.json` | `Assets/NatureManufacture Assets` of another Unity project (Unity 6) | `Assets/NatureManufacture` in the source's own folders, level `Bench_Parity_Nature` | `user/Parity_Nature` |

A bed's Unity project is the one its scope lies in; each is opened with the Editor of its own version.

A bed whose conversion project sets `mirror_source_folders` keeps the source's folders in its output: file names
repeat there, so the report calls a prefab by its path below the scope, and a scene's level lies below the scene's
folders (`Levels/<folders>/<scene>/<scene>.prefab`). The harness joins everything by guid and place, in both
layouts: the baked level names each converted prefab by the `Source` string the converter itself uses, read from
the bookkeeping the convert step leaves in the run folder.

A config's `work` names the bed's run folder under the O3DE project's `user/` (`Parity` when it names none). Give
every bed its own: the run folder holds the truth dump, the trace and the report, and two beds on one would write
over each other.

## The steps

| Step | What it does | Writes (under the bed's run folder) |
|---|---|---|
| `setup` | Registers the probe gem in the O3DE project. Build target `ParityProbe.Editor` after a configure. | - |
| `truth` | Unity truth dump, through `converter_cli.py truth`. Cached until a file of the scope changes. | `truth/<fingerprint>/` |
| `convert` | Both stages, through `converter_cli.py run`, with a seed and a trace. | `convert/` (log, trace, project copy) |
| `bake` | The measurement level: one instance of every converted prefab on a grid. Kept while it matches its recipe. | `Levels/Bench_Parity_<name>/` in the project |
| `cook` | `AssetProcessorBatch`. Failed jobs are listed by source asset and carried into the report. | `cook/` |
| `probe` | Editor session on the baked level, then on each converted scene's level. | `probe/` |
| `compare` | Joins the records, gives every element a verdict, groups the failures. | `report/` |
| `cycle` | All of the above, in order. | |

`--set stage.key=value` alters one cycle only (it is passed to the converter; the project file is not written).
`--only <wildcard>` narrows `convert` and `compare` to matching prefabs.

## Reading the report

`report/report.md` is the one to read; `report.json` holds everything behind it; `report/sheets/<prefab>.png` shows
each prefab from the front, the top and the left.

Each Unity object of a prefab has up to four kinds of element:

| Element | Passes when |
|---|---|
| `transform` | The entity's transform in the prefab frame is within the position and rotation tolerance, with the same scale. |
| `mesh` | The model sits where Unity's mesh sits: the placement fitted over all its vertices is within tolerance. |
| `collider` | The collision shape's geometry is where Unity's collider is. |
| `materials` | The renderer has the same materials by name. Which slot each is on is not checked. |

Other verdicts: `uncooked` (its assets did not cook), `unmatched` (no O3DE entity for the Unity object),
`unmeasured`, `lod_stripped` (a lower level of detail, dropped on purpose).

A failing element has a **residual**, the correction that would put it right, read as "do this to the O3DE
geometry": `shift (x, y, z) m`, `rot Z 180`, `mirror X`, `scale x0.01`, or a combination. Elements with the same kind
of residual on the same kind of FBX form a **cluster**. Fix a cluster in the converter, run a cycle, and the report's
last section says what closed, what opened and what regressed.

The "Mesh import" table sets each model, in its own space, against Unity's mesh in its own space. It separates what
the mesh import rule got wrong from what the entity's transform got wrong.

### Why meshes are judged by a fit

Unity moves vertices when a model is imported with mesh compression (the Office pack: High, on every file), by up to
a few millimetres. A vertex-by-vertex test would fail every mesh for Unity's own rounding. The harness instead fits
the rigid motion between the two vertex sets: noise averages out, a real offset or turn does not. The tolerances apply
to that fit.

## Frames

- Canonical frame: O3DE's. A Unity point `(x, y, z)` is `(x, z, y)`; a Unity transform `X` is `A X A`.
- Prefab frame: the prefab at zero position and identity rotation, with its root's stored scale.
- Residuals are in the prefab frame, in O3DE axes, in metres.

## The parts

| Part | File |
|---|---|
| Steps and folders | `parity.py` |
| Record readers | `records.py` |
| The math (frames, distances, fit, residual) | `compare.py` |
| Join, verdicts, clusters, report | `report.py` |
| Front, top, left drawings | `views.py` |
| Baked level and its recipe | `level_bake.py` |
| Cook and Editor session | `o3de_run.py`, `o3de/session.py` |
| Editor gem that writes what Python cannot read | `o3de/ParityProbe/` (console command `parity_dump <folder>`) |
| Unity side | `platforms/unity/bridge/` |
| Converter side | `converter_cli.py`, `stage_runner.py`, `conversion_trace.py` |

The harness needs `numpy` and `Pillow` (`parity/requirements.txt`). The converter itself does not.

## A new test bed

Copy `configs/office.json` and `configs/office.u2oproj.json`, point the project file at another scope and another
O3DE project, and give the level another name. The level is made by `bake`; a level folder without a
`parity_bake.json` was not made by this tool and is never touched.

## Limits

- The sheets are drawn from the two records. Rendered pictures from the two engines are not taken yet.
- Reading every component property in the Editor (`properties.json`) does not find components yet; the emitted
  values are in the trace.
- Material slots are compared as a set of names.
- Sphere, capsule and convex colliders are measured more loosely than boxes and triangle meshes (surface distance,
  bounds).
- An entity that serves Transform 2 is measured through its exact world matrix; the pack has none.
