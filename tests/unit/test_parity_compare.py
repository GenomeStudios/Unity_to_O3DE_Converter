"""Unit tests for the parity harness's math and level baker
(parity_harness I.3 and I.4; proofs T.10 and T.13).

Geometry is made up here: a lopsided cloud of points with no symmetry, so
every rotation and mirror of it is a different set.

Covers:
  - the Unity to O3DE frame mapping, for points and for transforms;
  - distances: equal sets are zero apart whatever their order and size;
  - the placement fit: it sees through vertex noise, and still sees a real
    offset or turn;
  - the residual search: a shift, a half turn, a mirror and a scale are each
    found and named;
  - rotation errors: an inverted rotation is told from other errors;
  - analytic collider shapes;
  - the level baker: recipe, refusals, and what it never touches.
"""

import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "parity"))

import numpy as np

from tests.harness import run_module_tests
import compare as cmp
import level_bake
import report
from records import matrix_from_trs, transform_points

TOLERANCE = 0.001   # one millimetre


# =============================================================================
# FIXTURES
# =============================================================================

def _cloud(count: int = 400, seed: int = 3) -> np.ndarray:
    """Points of a shape with no symmetry: a box stretched differently on
    each axis, with a lump on one corner."""
    random = np.random.default_rng(seed)
    points = random.uniform([0.0, 0.0, 0.0], [1.0, 0.4, 2.0], size=(count, 3))
    lump = random.uniform([0.9, 0.3, 1.8], [1.3, 0.5, 2.2], size=(count // 4, 3))
    return np.concatenate([points, lump])


def _quaternion(axis, degrees):
    axis = np.asarray(axis, dtype=float) / np.linalg.norm(axis)
    half = np.radians(degrees) / 2.0
    return list(axis * np.sin(half)) + [np.cos(half)]


def _rotation(axis, degrees) -> np.ndarray:
    return matrix_from_trs([0, 0, 0], _quaternion(axis, degrees), 1.0)[:3, :3]


# =============================================================================
# FRAMES
# =============================================================================

def test_unity_point_maps_by_swapping_y_and_z():
    mapped = cmp.unity_points_to_o3de(np.array([[1.0, 2.0, 3.0]]))
    assert mapped.tolist() == [[1.0, 3.0, 2.0]]


def test_transform_mapping_agrees_with_point_mapping():
    """Mapping a transform, then applying it to a mapped point, is the same
    as applying the Unity transform and mapping the result."""
    unity = matrix_from_trs([1.0, 2.0, 3.0], _quaternion([0.2, 1.0, 0.3], 37.0), [1.5, 0.5, 2.0])
    points = _cloud(20)
    direct = cmp.unity_points_to_o3de(transform_points(unity, points))
    through = transform_points(cmp.unity_matrix_to_o3de(unity), cmp.unity_points_to_o3de(points))
    assert np.allclose(direct, through, atol=1e-12)


def test_unity_yaw_keeps_its_direction_in_o3de():
    """A Unity object turned +90 about Y faces +X. Its O3DE transform must
    make the mapped forward axis (+Y) face +X as well."""
    unity = matrix_from_trs([0, 0, 0], _quaternion([0, 1, 0], 90.0), 1.0)
    forward = cmp.unity_matrix_to_o3de(unity)[:3, :3] @ np.array([0.0, 1.0, 0.0])
    assert np.allclose(forward, [1.0, 0.0, 0.0], atol=1e-12)


def test_prefab_frame_takes_out_position_and_rotation_and_keeps_scale():
    root = matrix_from_trs([5.0, 6.0, 7.0], _quaternion([0, 1, 0], 30.0), [2.0, 2.0, 2.0])
    in_frame = cmp.prefab_frame(root) @ root
    assert np.allclose(in_frame, np.diag([2.0, 2.0, 2.0, 1.0]), atol=1e-12)


# =============================================================================
# DISTANCES
# =============================================================================

def test_equal_sets_are_zero_apart_in_any_order():
    points = _cloud()
    shuffled = points[np.random.default_rng(1).permutation(len(points))]
    # The distance formula loses a few hundredths of a micrometre to rounding.
    assert cmp.two_way_distance(points, shuffled)["max_mm"] < 1e-3


def test_sampling_does_not_separate_equal_sets():
    points = _cloud(9000)
    assert cmp.two_way_distance(points, points.copy(), limit=500)["max_mm"] < 1e-3


def test_a_two_millimetre_shift_is_measured():
    points = _cloud()
    distance = cmp.two_way_distance(points + [0.002, 0.0, 0.0], points)
    assert 0.5 < distance["max_mm"] <= 2.0 + 1e-6


def test_missing_geometry_is_infinitely_far():
    assert cmp.two_way_distance(_cloud(), np.zeros((0, 3)))["max_mm"] == float("inf")


# =============================================================================
# PLACEMENT FIT
# =============================================================================

def test_fit_sees_through_vertex_noise():
    """Three millimetres of noise on every vertex, no offset: in place."""
    expected = _cloud(600)
    noisy = expected + np.random.default_rng(5).uniform(-0.003, 0.003, size=expected.shape)
    fit = cmp.fit_placement(noisy, expected, cmp.noise_gate(expected, TOLERANCE))
    assert fit["matched"] > 0.97, fit
    assert fit["offset_mm"] < 1.0 and fit["rotation_deg"] < 0.1, fit
    assert abs(fit["scale"] - 1.0) < 0.005, fit


def test_fit_measures_an_offset_under_the_same_noise():
    expected = _cloud(600)
    noisy = expected + np.random.default_rng(5).uniform(-0.003, 0.003, size=expected.shape)
    fit = cmp.fit_placement(noisy + [0.004, 0.0, 0.0], expected, cmp.noise_gate(expected, TOLERANCE))
    assert 3.0 < fit["offset_mm"] < 5.0, fit


def test_fit_measures_a_small_turn():
    expected = _cloud(600)
    centre = expected.mean(axis=0)
    turned = (expected - centre) @ _rotation([0, 0, 1], 0.5).T + centre
    fit = cmp.fit_placement(turned, expected, cmp.noise_gate(expected, TOLERANCE))
    assert 0.4 < fit["rotation_deg"] < 0.6, fit


def test_fit_reports_unmatched_geometry():
    expected = _cloud(600)
    fit = cmp.fit_placement(expected + [5.0, 0.0, 0.0], expected, cmp.noise_gate(expected, TOLERANCE))
    assert fit["matched"] < 0.5 and fit["offset_mm"] == float("inf"), fit


# =============================================================================
# RESIDUAL SEARCH
# =============================================================================

def _pencil(count: int = 300, seed: int = 5) -> np.ndarray:
    """Points of a thin rod along X: 15 cm long, 3 mm thick."""
    generator = np.random.default_rng(seed)
    return np.column_stack([generator.uniform(-0.075, 0.075, count),
                            generator.uniform(-0.0015, 0.0015, count),
                            generator.uniform(-0.0015, 0.0015, count)])


def test_reach_from_an_axis_is_small_along_a_rod_and_large_across_it():
    rod = _pencil()
    along = cmp.spread_about_axis(rod, [1.0, 0.0, 0.0])
    across = cmp.spread_about_axis(rod, [0.0, 0.0, 1.0])
    assert along < 0.002 < 0.03 < across
    assert abs(cmp.spread_about_axis(rod, None) - np.sqrt(along ** 2 + rod[:, 0].var())) < 1e-6


class _Tolerance:
    tolerance = {"position_mm": 1.0, "rotation_deg": 0.1, "geometry_mm": 1.0}


def test_a_rod_turned_about_its_length_within_its_noise_is_in_place():
    """The pencil of the Office pack: a fit of a thin mesh turns about its
    length by a third of a degree on noise of a twentieth of a millimetre."""
    rod = _pencil()
    fit = {"matched": 1.0, "offset_mm": 0.02, "rotation_deg": 0.37, "noise_mm": 0.05,
           "rotation_axis": [1.0, 0.0, 0.0]}
    assert report.placement_verdict(_Tolerance, fit, rod) == (True, False)
    # The same turn about an axis across the rod moves its ends by half a millimetre: not noise.
    across = dict(fit, rotation_axis=[0.0, 0.0, 1.0])
    assert report.placement_verdict(_Tolerance, across, rod) == (False, False)


def test_an_offset_beyond_tolerance_and_noise_is_not_in_place():
    rod = _pencil()
    fit = {"matched": 1.0, "offset_mm": 2.5, "rotation_deg": 0.0, "noise_mm": 0.3, "rotation_axis": None}
    assert report.placement_verdict(_Tolerance, fit, rod) == (False, False)
    assert report.placement_verdict(_Tolerance, dict(fit, offset_mm=1.2), rod) == (True, False)
    assert report.placement_verdict(_Tolerance, dict(fit, offset_mm=0.4), rod) == (True, True)
    assert report.placement_verdict(_Tolerance, dict(fit, offset_mm=0.4, matched=0.5), rod) == (False, False)


def test_the_fit_names_the_axis_it_turns_about():
    expected = _cloud(600)
    centre = expected.mean(axis=0)
    turned = (expected - centre) @ _rotation([0, 0, 1], 0.5).T + centre
    fit = cmp.fit_placement(turned, expected, cmp.noise_gate(expected, TOLERANCE))
    assert abs(abs(fit["rotation_axis"][2]) - 1.0) < 1e-3, fit


# =============================================================================
# MATERIALS
# =============================================================================

def _material(name, path):
    return {"name": name, "guid": "0" * 32, "assetPath": path}


def _traced_with(hints):
    return {"components": [{"emitted": {"materials": [{"assetHint": hint} for hint in hints]}}]}


def test_unitys_default_material_is_not_asked_for():
    """A cube made in the Unity editor carries Unity's own material, which is
    no asset of the project: nothing can be converted, nothing is missing."""
    item = {"materials": [_material("Lit", "Packages/com.unity.render-pipelines.universal/Runtime/Materials/Lit.mat")]}
    element = report.material_element(item, _traced_with([]))
    assert element["status"] == "pass" and element["unity_not_project_assets"] == ["lit"]


def test_a_project_material_that_is_missing_still_fails():
    item = {"materials": [_material("Wall", "Assets/Pack/Materials/Wall.mat"),
                          _material("Lit", "Packages/urp/Lit.mat")]}
    assert report.material_element(item, _traced_with([]))["status"] == "fail"
    passed = report.material_element(item, _traced_with(["assets/pack/materials/wall.azmaterial"]))
    assert passed["status"] == "pass"


# =============================================================================
# A LEVEL'S AMBIENT LIGHT
# =============================================================================

_SCENE_TEXT = """--- !u!104 &2
RenderSettings:
  m_AmbientSkyColor: {r: 0.212, g: 0.227, b: 0.259, a: 1}
  m_AmbientEquatorColor: {r: 0.114, g: 0.125, b: 0.133, a: 1}
  m_AmbientGroundColor: {r: 0.047, g: 0.043, b: 0.035, a: 1}
  m_AmbientMode: 0
"""


_SCENE_WITHOUT_AMBIENT = """--- !u!104 &2
RenderSettings:
  m_Fog: 0
"""


def _lighting_row(held_components: dict, scene_text: str = _SCENE_TEXT):
    """Run report.lighting_row on a scene file and a probe's properties.json
    made up for the test. ``held_components``: {entity id: {path: value}}."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "Assets").mkdir()
        (root / "Assets" / "Gallery.unity").write_text(scene_text, encoding="utf-8")
        (root / "properties.json").write_text(json.dumps(
            {entity_id: {report.GRADIENT_GI: values} for entity_id, values in held_components.items()}),
            encoding="utf-8")

        class _Truth:
            catalog = {"projectPath": str(root)}

        class _Cycle:
            truth = _Truth()

        return report.lighting_row(_Cycle(), {"assetPath": "Assets/Gallery.unity"}, root)


_HELD = {"Controller|Configuration|Gradient Colors|High (Zenith)": "(r=0.2120000,g=0.2270000,b=0.2590000,a=1.0000000)",
         "Controller|Configuration|Gradient Colors|Mid (Horizon)": "(r=0.1140000,g=0.1250000,b=0.1330000,a=1.0000000)",
         "Controller|Configuration|Gradient Colors|Low (Nadir)":   "(r=0.0470000,g=0.0430000,b=0.0350000,a=1.0000000)",
         "Controller|Configuration|Settings|Exposure": "0.0"}


def test_the_ambient_colours_are_read_from_the_scene_file():
    with tempfile.TemporaryDirectory() as folder:
        scene = Path(folder) / "Gallery.unity"
        scene.write_text(_SCENE_TEXT, encoding="utf-8")
        assert report.unity_ambient_colours(scene)["m_AmbientGroundColor"] == [0.047, 0.043, 0.035]
        scene.write_text(_SCENE_WITHOUT_AMBIENT, encoding="utf-8")
        assert report.unity_ambient_colours(scene) is None


def test_a_level_holding_the_scenes_three_colours_passes_its_lighting():
    row = _lighting_row({"7": _HELD})
    assert row["status"] == "pass" and row["source"] == "(scene lighting)"


def test_a_wrong_colour_or_a_missing_component_fails_the_lighting():
    wrong = dict(_HELD, **{"Controller|Configuration|Gradient Colors|Low (Nadir)": "(r=0.5,g=0.5,b=0.5,a=1.0)"})
    row = _lighting_row({"7": wrong})
    assert row["status"] == "fail" and "Low is" in row["residual"]
    assert "0 Gradient GI component(s)" in _lighting_row({})["residual"]
    assert "2 Gradient GI component(s)" in _lighting_row({"7": _HELD, "8": _HELD})["residual"]


def test_a_scene_without_ambient_colours_has_no_lighting_row():
    assert _lighting_row({"7": _HELD}, scene_text=_SCENE_WITHOUT_AMBIENT) is None


def _residual(actual, expected):
    residual = cmp.find_residual(actual, expected, TOLERANCE)
    return residual, cmp.residual_class(residual, TOLERANCE)


def test_equal_sets_need_nothing():
    points = _cloud()
    residual, kind = _residual(points, points.copy())
    assert residual["found"] and kind == "none"
    assert cmp.describe_residual(residual, TOLERANCE) == "none"


def test_a_shift_is_found_with_its_value():
    expected = _cloud()
    residual, kind = _residual(expected - [0.002, 0.5, -0.25], expected)
    assert residual["found"] and kind == "shift", residual
    assert np.allclose(residual["shift"], [0.002, 0.5, -0.25], atol=1e-6)


def test_a_half_turn_about_z_is_named():
    expected = _cloud()
    actual = expected @ _rotation([0, 0, 1], 180.0).T          # the mesh, turned
    residual, kind = _residual(actual, expected)
    assert residual["found"] and residual["name"] == "rot Z 180", residual
    assert kind.startswith("rot Z 180")


def test_a_quarter_turn_about_x_is_named_with_its_sense():
    expected = _cloud()
    actual = expected @ _rotation([1, 0, 0], 90.0).T + [0.3, 0.0, 0.0]
    residual, _ = _residual(actual, expected)
    assert residual["found"] and residual["name"] == "rot X -90", residual


def test_a_mirror_is_named():
    expected = _cloud()
    residual, kind = _residual(expected * [-1.0, 1.0, 1.0], expected)
    assert residual["found"] and residual["name"] == "mirror X", residual
    assert kind.startswith("mirror X")


def test_a_scale_is_found():
    expected = _cloud()
    residual, kind = _residual(expected * 100.0, expected)
    assert residual["found"] and abs(residual["scale"] - 0.01) < 1e-9, residual
    assert "scale" in kind


def test_an_arbitrary_turn_is_reported_as_unexplained():
    expected = _cloud()
    actual = expected @ _rotation([0.3, 1.0, 0.2], 33.0).T
    residual, kind = _residual(actual, expected)
    assert not residual["found"] and kind == "unexplained"
    assert "no axis-aligned correction" in cmp.describe_residual(residual, TOLERANCE)


def test_the_48_permutations_have_distinct_names():
    names = [name for _, name in cmp.SIGNED_PERMUTATIONS]
    assert len(names) == 48 and len(set(names)) == 48
    assert names[0] == "identity"


# =============================================================================
# TRANSFORM AND ROTATION ERRORS
# =============================================================================

def test_equal_transforms_have_no_delta():
    matrix = matrix_from_trs([1, 2, 3], _quaternion([0, 0, 1], 40.0), [1, 2, 3])
    delta = cmp.transform_delta(matrix, matrix.copy())
    assert delta["position_mm"] < 1e-9 and delta["rotation_deg"] < 1e-6
    assert delta["rotation_class"] == "none" and delta["scale_error"] < 1e-12


def test_an_inverted_rotation_is_named():
    expected = matrix_from_trs([0, 0, 0], _quaternion([0, 0, 1], 30.0), 1.0)
    actual = matrix_from_trs([0, 0, 0], _quaternion([0, 0, 1], -30.0), 1.0)
    delta = cmp.transform_delta(expected, actual)
    assert abs(delta["rotation_deg"] - 60.0) < 1e-6
    assert delta["rotation_class"] == "inverted"


def test_other_rotation_errors_are_told_apart():
    expected = matrix_from_trs([0, 0, 0], _quaternion([0, 0, 1], 30.0), 1.0)
    half_turn = expected @ matrix_from_trs([0, 0, 0], _quaternion([0, 0, 1], 180.0), 1.0)
    assert cmp.transform_delta(expected, half_turn)["rotation_class"] == "rot Z 180"
    odd = matrix_from_trs([0, 0, 0], _quaternion([1, 0, 0], 17.0), 1.0)
    assert cmp.transform_delta(expected, odd)["rotation_class"] == "other"


def test_lost_scale_and_position_are_measured():
    expected = matrix_from_trs([1.0, 0.0, 0.0], [0, 0, 0, 1], [2.0, 2.0, 2.0])
    actual = matrix_from_trs([1.0, 0.0, 0.005], [0, 0, 0, 1], 1.0)
    delta = cmp.transform_delta(expected, actual)
    assert abs(delta["position_mm"] - 5.0) < 1e-6
    assert abs(delta["scale_error"] - 0.5) < 1e-9


def test_a_mirror_is_reported_as_a_mismatch():
    plain = np.identity(4)
    mirrored = np.diag([-1.0, 1.0, 1.0, 1.0])
    assert cmp.transform_delta(plain, mirrored)["mirror_mismatch"]
    assert not cmp.transform_delta(mirrored, mirrored.copy())["mirror_mismatch"]


# =============================================================================
# ANALYTIC SHAPES
# =============================================================================

def test_points_on_a_sphere_and_a_capsule_are_on_the_surface():
    directions = np.random.default_rng(2).normal(size=(200, 3))
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    on_sphere = np.array([1.0, 2.0, 3.0]) + 0.5 * directions
    assert cmp.sphere_surface_distances(on_sphere, [1.0, 2.0, 3.0], 0.5).max() < 1e-12
    assert abs(cmp.sphere_surface_distances(on_sphere, [1.0, 2.0, 3.0], 0.6).max() - 0.1) < 1e-12

    # A capsule along Z: points on its side wall and on its top cap.
    side = np.array([[0.25, 0.0, 0.3], [0.0, -0.25, 0.9]])
    cap = np.array([[0.0, 0.0, 1.25]])
    distances = cmp.capsule_surface_distances(np.concatenate([side, cap]), [0, 0, 0], [0, 0, 1], 0.25)
    assert distances.max() < 1e-12


# =============================================================================
# DIFFERENCE BETWEEN TWO REPORTS
# =============================================================================

def _report(statuses: dict, signatures=()) -> dict:
    """A report with one prefab holding one object per given element."""
    objects = [{"index": index, "path": path, "elements": [{"kind": "mesh", "status": status}]}
               for index, (path, status) in enumerate(statuses.items())]
    return {"prefabs": [{"name": "Desk", "objects": objects}],
            "clusters": [{"signature": signature} for signature in signatures]}


def test_difference_names_regressions_and_fixes():
    before = _report({"Desk/Frame": "pass", "Desk/Drawer": "fail", "Desk/Door": "pass", "Desk/Lid": "uncooked"},
                     ["mesh: shift"])
    after = _report({"Desk/Frame": "fail", "Desk/Drawer": "pass", "Desk/Door": "uncooked", "Desk/Lid": "pass"},
                    ["mesh: rot Z 180"])
    change = report.difference(before, after)
    assert change["regressions"] == ["Desk / Desk/Door #2 / mesh 1", "Desk / Desk/Frame #0 / mesh 1"]
    assert change["fixed"] == ["Desk / Desk/Drawer #1 / mesh 1", "Desk / Desk/Lid #3 / mesh 1"]
    assert change["clusters_closed"] == ["mesh: shift"]
    assert change["clusters_opened"] == ["mesh: rot Z 180"]


def test_difference_of_equal_reports_is_empty():
    same = _report({"Desk/Frame": "pass", "Desk/Drawer": "fail"}, ["mesh: shift"])
    assert not any(report.difference(same, same).values())


# =============================================================================
# LEVEL BAKER
# =============================================================================

def _make_o3de_project(root: Path) -> list:
    """A project with a default level and two converted prefabs."""
    (root / "Levels" / "DefaultLevel").mkdir(parents=True)
    (root / "Levels" / "DefaultLevel" / "DefaultLevel.prefab").write_text(json.dumps({
        "ContainerEntity": {"Id": "Entity_[1]", "Name": "Level", "Components": {
            "Sort": {"$type": "EditorEntitySortComponent", "Child Entity Order": ["Entity_[2]", "Entity_[3]"]}}},
        "Entities": {
            "Entity_[2]": {"Name": "Sun", "Components": {}},
            "Entity_[3]": {"Name": "Ground", "Components": {}},
        },
    }), encoding="utf-8")
    prefabs = root / "Assets" / "Pack" / "Prefabs"
    prefabs.mkdir(parents=True)
    (prefabs / "Desk.prefab").write_text(json.dumps({
        "Instances": {"Instance_[9]": {"Source": "assets/pack/prefabs/Drawer.prefab", "Patches": []}}}),
        encoding="utf-8")
    (prefabs / "Drawer.prefab").write_text(json.dumps({"Instances": {}}), encoding="utf-8")
    return sorted(prefabs.glob("*.prefab"))


def test_recipe_lays_prefabs_out_without_overlap():
    with tempfile.TemporaryDirectory() as tmp:
        prefabs = _make_o3de_project(Path(tmp))
        recipe = level_bake.make_recipe(Path(tmp), prefabs, {"Desk": 3.0, "Drawer": 0.5})
        assert recipe["spacing"] == 8.0                      # twice the largest reach, plus two
        cells = [cell["cell"] for cell in recipe["instances"]]
        assert abs(cells[0][0] - cells[1][0]) >= recipe["spacing"]
        assert [cell["source"] for cell in recipe["instances"]] == [
            "Assets/Pack/Prefabs/Desk.prefab", "Assets/Pack/Prefabs/Drawer.prefab"]


def test_level_names_prefabs_the_way_they_name_each_other():
    with tempfile.TemporaryDirectory() as tmp:
        prefabs = _make_o3de_project(Path(tmp))
        folder = level_bake.nested_source_folder(prefabs)
        assert folder == "assets/pack/prefabs"
        recipe = level_bake.make_recipe(Path(tmp), prefabs, {}, folder)
        assert recipe["instances"][0]["source"] == "assets/pack/prefabs/Desk.prefab"


def test_bake_writes_level_and_recipe():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        recipe = level_bake.make_recipe(root, _make_o3de_project(root), {})
        level_file = level_bake.bake_level(root, "Bench_Test", recipe)
        level = json.loads(level_file.read_text(encoding="utf-8"))

        assert [entity["Name"] for entity in level["Entities"].values()] == ["Sun"], "Ground must be dropped"
        assert level["ContainerEntity"]["Components"]["Sort"]["Child Entity Order"] == ["Entity_[2]"]
        assert len(level["Instances"]) == 2
        patches = level["Instances"]["Instance_[1000000]"]["Patches"]
        assert patches[0]["value"] == "../Entity_[1]"
        assert [patch["value"] for patch in patches[1:]] == recipe["instances"][0]["cell"]
        assert level_bake.recipe_problem(root / "Levels" / "Bench_Test", recipe) == ""


def test_a_changed_recipe_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prefabs = _make_o3de_project(root)
        level_bake.bake_level(root, "Bench_Test", level_bake.make_recipe(root, prefabs, {}))

        (prefabs[0].parent / "Chair.prefab").write_text("{}", encoding="utf-8")
        wider = level_bake.make_recipe(root, sorted(prefabs[0].parent.glob("*.prefab")), {})
        problem = level_bake.recipe_problem(root / "Levels" / "Bench_Test", wider)
        assert "no longer matches its recipe" in problem

        assert "has not been baked" in level_bake.recipe_problem(root / "Levels" / "Missing", wider)


def test_a_level_without_a_recipe_is_never_touched():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        recipe = level_bake.make_recipe(root, _make_o3de_project(root), {})
        own = root / "Levels" / "MyLevel"
        own.mkdir()
        (own / "MyLevel.prefab").write_text("mine", encoding="utf-8")

        assert "was not made by this tool" in level_bake.recipe_problem(own, recipe)
        try:
            level_bake.bake_level(root, "MyLevel", recipe)
            raise AssertionError("baking over a level without a recipe must be refused")
        except RuntimeError as refusal:
            assert "left alone" in str(refusal)
        assert (own / "MyLevel.prefab").read_text(encoding="utf-8") == "mine"


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
