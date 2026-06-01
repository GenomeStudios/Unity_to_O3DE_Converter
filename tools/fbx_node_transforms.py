"""CLI: dump per-node Lcl Translation/Rotation/Scaling from binary FBX(s).

Thin wrapper over `integrated_asset_processor.read_fbx_node_transforms`
(the production reader). Reveals the FBX-baked node offsets behind the
cross-pack placement scatter. See `mem:transform_truth/transform_truth_plan`.

  python tools/fbx_node_transforms.py <file.fbx> [more.fbx ...]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integrated_asset_processor import read_fbx_node_transforms


def dump(path: str) -> None:
    nodes = read_fbx_node_transforms(Path(path))
    print(f"\n=== {Path(path).name} ===")
    if not nodes:
        print("  (no Model nodes / not a binary FBX)")
        return
    for name, tr in nodes.items():
        t = [round(v, 3) for v in tr["translation"]]
        r = [round(v, 3) for v in tr["rotation"]]
        s = [round(v, 3) for v in tr["scaling"]]
        print(f"  {name:42} T(cm)={t}  R(deg)={r}  S={s}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    for arg in sys.argv[1:]:
        dump(arg)
