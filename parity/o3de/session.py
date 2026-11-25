"""
=============================================================================
PARITY PROBE SESSION
=============================================================================

Runs inside the O3DE Editor (``Editor --runpython session.py --runpythonargs
<run folder>``), started by ``parity/o3de_run.py``.

    1. opens the level named in <run folder>/session.json (never saves it);
    2. runs the probe gem's console command ``parity_dump`` until every
       model is loaded, or the tries are used up;
    3. reads every property of the components the converter emits;
    4. leaves the Editor.

Writes <run folder>/progress.json while it works and <run folder>/result.json
at the end. The launcher watches both and kills an Editor that stops.
"""

import json
import os
import sys
import time
import traceback

# Components whose properties are read, by the name the Editor shows.
SCRUBBED_COMPONENTS = [
    "Mesh", "Material", "Non-uniform Scale",
    "PhysX Static Rigid Body", "PhysX Dynamic Rigid Body",
    "PhysX Primitive Collider", "PhysX Mesh Collider", "PhysX Shape Collider",
    "Box Shape", "Sphere Shape", "Capsule Shape",
    "Directional Light", "Light",
]


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def main():
    run_dir = sys.argv[1]
    result = {"status": "failed", "steps": {}, "errors": []}
    general = None

    def progress(phase):
        write_json(os.path.join(run_dir, "progress.json"),
                   {"phase": phase, "time": time.strftime("%H:%M:%S"), "pid": os.getpid()})

    try:
        progress("started")
        config = read_json(os.path.join(run_dir, "session.json"))
        out_dir = config["out"].replace("\\", "/")

        import azlmbr.legacy.general as general_module
        general = general_module
        general.idle_enable(True)       # frames advance while the script waits
        general.idle_wait(2.0)

        # ----- The level -----------------------------------------------------
        progress("level")
        level_name = config["level"]
        general.open_level_no_prompt(level_name)
        waited = 0.0
        while general.get_current_level_name() != level_name and waited < 300.0:
            general.idle_wait(1.0)
            waited += 1.0
        result["steps"]["level"] = general.get_current_level_name()
        result["steps"]["level_open_seconds"] = waited
        if result["steps"]["level"] != level_name:
            raise RuntimeError("the level '%s' did not open" % level_name)
        general.idle_wait(float(config.get("settle_seconds", 5.0)))

        # ----- The probe -----------------------------------------------------
        # Models load in the background after the level opens. The dump is
        # repeated until none is missing or the count stops going down.
        done_file = os.path.join(out_dir, "probe_done.json")
        done, tries = None, 0
        last_missing, same_count = None, 0
        while tries < int(config.get("dump_tries", 30)):
            tries += 1
            progress("probe %d" % tries)
            if os.path.isfile(done_file):
                os.remove(done_file)
            general.run_console("parity_dump %s" % out_dir)
            waited = 0.0
            while not os.path.isfile(done_file) and waited < 120.0:
                general.idle_wait(0.5)
                waited += 0.5
            done = read_json(done_file)
            if done is None:
                raise RuntimeError("parity_dump wrote no probe_done.json: is the ParityProbe gem built and enabled?")
            if done["meshesNotReady"] == 0:
                break
            same_count = same_count + 1 if done["meshesNotReady"] == last_missing else 0
            last_missing = done["meshesNotReady"]
            if same_count >= int(config.get("give_up_after_same", 6)):
                break
            general.idle_wait(5.0)
        result["steps"]["probe_tries"] = tries
        result["steps"]["probe"] = done

        # ----- Component properties ------------------------------------------
        if config.get("scrub", True):
            progress("scrub")
            result["steps"]["scrub"] = scrub_components(out_dir, result["errors"])

        result["status"] = "ok"
    except Exception:
        result["errors"].append(traceback.format_exc())
    finally:
        write_json(os.path.join(run_dir, "result.json"), result)
        progress("done")
        if general is not None:
            general.exit_no_prompt()


def scrub_components(out_dir, errors):
    """Read every property of the scrubbed components of every probed entity
    into <out>/properties.json: ``{entity id: {component: {path: value}}}``."""
    import azlmbr.bus as bus
    import azlmbr.editor as editor
    import azlmbr.entity as entity

    record = read_json(os.path.join(out_dir, "record.json"))
    type_ids = editor.EditorComponentAPIBus(
        bus.Broadcast, "FindComponentTypeIdsByEntityType", SCRUBBED_COMPONENTS, entity.EntityType().Game)
    known = [(name, type_id) for name, type_id in zip(SCRUBBED_COMPONENTS, type_ids)]

    # Entity ids as the Editor hands them out, by their number: the record
    # holds the numbers, the component calls want the Editor's own objects.
    by_number = {}
    for entity_id in entity.SearchBus(bus.Broadcast, "SearchEntities", entity.SearchFilter()):
        by_number[entity_id.ToString().strip("[]")] = entity_id

    properties, components_read, failures = {}, 0, 0
    for item in record["entities"]:
        entity_id = by_number.get(item["id"])
        if entity_id is None:
            continue
        found = {}
        for name, type_id in known:
            try:
                outcome = editor.EditorComponentAPIBus(bus.Broadcast, "GetComponentOfType", entity_id, type_id)
                if not outcome.IsSuccess():
                    continue
                component = outcome.GetValue()
                values = {}
                for path in editor.EditorComponentAPIBus(bus.Broadcast, "BuildComponentPropertyList", component):
                    value = editor.EditorComponentAPIBus(bus.Broadcast, "GetComponentProperty", component, path)
                    values[path] = str(value.GetValue()) if value.IsSuccess() else None
                found[name] = values
                components_read += 1
            except Exception:
                failures += 1
                if failures <= 3:
                    errors.append("scrub of '%s' on %s: %s" % (name, item["name"], traceback.format_exc(limit=1)))
        if found:
            properties[item["id"]] = found

    write_json(os.path.join(out_dir, "properties.json"), properties)
    return {"entities": len(properties), "components": components_read, "failures": failures}


if __name__ == "__main__":
    main()
