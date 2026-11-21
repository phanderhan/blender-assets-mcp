"""ambientCG: CC0 PBR materials and HDRIs (https://ambientcg.com)."""
import tempfile
import zipfile
from pathlib import Path

from . import snippets
from .common import CC0, cached_asset, copy_limited, download, get_json, inside

TYPES = {"material": "Material", "hdri": "HDRI"}
# Map file name markers, using the OpenGL normal map that Blender expects.
MAPS = {
    "color": "_Color.", "normal": "_NormalGL.", "roughness": "_Roughness.",
    "metalness": "_Metalness.", "displacement": "_Displacement.", "opacity": "_Opacity.",
}


def query(params: dict) -> list[dict]:
    data = get_json("https://ambientcg.com/api/v2/full_json", {"include": "downloadData,tagData", **params})
    return data.get("foundAssets", [])


def search(text: str, kinds: list[str], limit: int) -> list[dict]:
    types = [TYPES[k] for k in kinds if k in TYPES]
    if not types:
        return []
    assets = query({"q": text, "type": ",".join(types), "sort": "Popular", "limit": limit})
    return [
        {
            "source": "ambientcg",
            "id": a["assetId"],
            "name": a.get("displayName") or a["assetId"],
            "kind": "hdri" if a["dataType"] == "HDRI" else "material",
            "license": CC0,
            "author": "ambientCG",
            "page": a.get("shortLink") or f"https://ambientcg.com/view?id={a['assetId']}",
            "thumbnail": (a.get("previewImage") or {}).get("256-PNG", ""),
        }
        for a in assets
        if a.get("dataType") in types
    ]


def extract(archive: Path, root: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        if len(members) > 256 or sum(m.file_size for m in members) > 1024 * 1024 * 1024:
            raise ValueError("archive exceeds resource limits")
        for member in members:
            if (member.file_size > 512 * 1024 * 1024 or
                    (member.file_size > 1024 * 1024
                     and member.file_size > 100 * max(member.compress_size, 1))):
                raise ValueError("archive member exceeds resource limits")
            if member.is_dir():
                continue
            target = inside(root, member.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as dst:
                copy_limited(src, dst, min(member.file_size, 512 * 1024 * 1024))


def fetch(asset_id: str, resolution: str) -> dict:
    found = [a for a in query({"id": asset_id}) if a["assetId"] == asset_id]
    if not found:
        raise ValueError(f"unknown ambientCG asset: {asset_id}")
    asset = found[0]
    if asset["dataType"] not in TYPES.values():
        raise ValueError(f"{asset_id} is a {asset['dataType']}; only materials and HDRIs are supported")
    kind = "hdri" if asset["dataType"] == "HDRI" else "material"
    downloads = asset["downloadFolders"]["default"]["downloadFiletypeCategories"]["zip"]["downloads"]
    wanted = resolution.upper() if kind == "hdri" else f"{resolution.upper()}-JPG"
    choice = next((d for d in downloads if d["attribute"] == wanted), None)
    if choice is None:
        raise ValueError(f"{asset_id} has no {wanted} download; available: {[d['attribute'] for d in downloads]}")
    def populate(root):
        with tempfile.TemporaryDirectory() as tmp:
            extract(download(choice["downloadLink"], Path(tmp) / "asset.zip"), root)
        files = [p for p in root.rglob("*") if p.is_file()]
        if kind == "hdri":
            main = next((p for p in files if p.suffix.lower() in (".exr", ".hdr")), None)
            if main is None:
                raise ValueError("asset has no HDRI file")
            return str(main.relative_to(root))
        if not any(marker in p.name and p.suffix.lower() in (".jpg", ".png")
                   for p in files for marker in MAPS.values()):
            raise ValueError("asset has no texture maps")
        return ""

    root, main_rel = cached_asset("ambientcg", asset_id, resolution, {"kind": kind, "license": CC0}, populate,
                                  allow_directory=kind == "material")
    files = [p for p in root.rglob("*") if p.is_file()]
    if kind == "hdri":
        main = inside(root, main_rel)
        code = snippets.set_world_hdri(main)
    else:
        maps = {
            key: p for key, marker in MAPS.items()
            for p in files if marker in p.name and p.suffix.lower() in (".jpg", ".png")
        }
        main = root
        code = snippets.build_material(asset_id, maps)
    return {
        "kind": kind,
        "path": str(main),
        "license": CC0,
        "attribution": f"{asset_id}, ambientCG.com (CC0)",
        "blender_python": code,
    }
