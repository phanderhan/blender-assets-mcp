"""BlenderKit, free assets only (https://www.blenderkit.com).

Free assets download without an account. Paid assets are refused even when the API
would serve them, so agents can't pull something that needs a subscription.
"""
import uuid

from . import snippets
from .common import CC0, cached_asset, download, get_json, inside, url_filename

API = "https://www.blenderkit.com/api/v1"
TYPES = {"model": "model", "material": "material", "hdri": "hdr"}
KINDS = {v: k for k, v in TYPES.items()}
LICENSES = {
    "cc_zero": CC0,
    "royalty_free": "BlenderKit Royalty Free: use in any project, including commercial; "
    "do not resell or share the asset file itself",
}


def query(text: str, page_size: int) -> list[dict]:
    return get_json(f"{API}/search/", {"query": text, "page_size": page_size}).get("results", [])


def license_text(asset: dict) -> str:
    return LICENSES.get(asset.get("license", ""), asset.get("license", ""))


def search(text: str, kinds: list[str], limit: int) -> list[dict]:
    # One query for several kinds; BlenderKit ranks across asset types itself.
    type_filter = f" asset_type:{TYPES[kinds[0]]}" if len(kinds) == 1 else ""
    results = query(f"{text}{type_filter} is_free:true".strip(), limit * 2)
    wanted = {TYPES[k] for k in kinds}
    results = [r for r in results if r.get("isFree") and r.get("assetType") in wanted][:limit]
    return [
        {
            "source": "blenderkit",
            "id": r["assetBaseId"],
            "name": r.get("name", ""),
            "kind": KINDS[r["assetType"]],
            "license": license_text(r),
            "author": (r.get("author") or {}).get("fullName", ""),
            "description": (r.get("description") or "")[:200],
            "thumbnail": r.get("thumbnailMiddleUrl", ""),
        }
        for r in results
    ]


def fetch(asset_id: str, resolution: str) -> dict:
    found = query(f"asset_base_id:{asset_id}", 1)
    if not found:
        raise ValueError(f"unknown BlenderKit asset: {asset_id}")
    asset = found[0]
    if asset.get("assetBaseId") != asset_id:
        raise ValueError("BlenderKit asset identity mismatch")
    if asset.get("license") not in LICENSES:
        raise ValueError("unknown BlenderKit asset license")
    if asset.get("isFree") is not True:
        raise ValueError(f"{asset['name']} is not a free BlenderKit asset; only free assets are allowed")
    kind = KINDS.get(asset["assetType"])
    if kind is None:
        raise ValueError(f"{asset['name']} is a {asset['assetType']}; only models, materials and HDRIs are supported")
    files = {f["fileType"]: f["downloadUrl"] for f in asset["files"]}
    file_type = "blend" if resolution == "original" else "resolution_" + resolution.upper().replace(".", "_")
    if file_type not in files:
        file_type = "blend"  # assets without downscaled variants
    def populate(root):
        # The API answers with a short-lived signed URL; any scene id works for anonymous downloads.
        signed = get_json(files[file_type], {"scene_uuid": str(uuid.uuid4())})["filePath"]
        main = download(signed, root / url_filename(signed))
        return str(main.relative_to(root))

    provenance = {"kind": kind, "license": asset["license"], "file_type": file_type,
                  "version": asset.get("id"), "name": asset.get("name", asset_id),
                  "author": (asset.get("author") or {}).get("fullName", "unknown")}
    root, main_rel = cached_asset("blenderkit", asset_id, resolution, provenance, populate)
    main = inside(root, main_rel)
    name = asset.get("name", asset_id)
    # HDRI "resolution" files are plain .exr images, whatever their file type says.
    if kind == "hdri" or main.suffix.lower() in (".exr", ".hdr"):
        code = snippets.set_world_hdri(main)
    elif kind == "material":
        code = snippets.import_blend_materials(main)
    else:
        code = snippets.import_blend_objects(main, name)
    lic = license_text(asset)
    author = (asset.get("author") or {}).get("fullName", "unknown")
    return {
        "kind": kind,
        "path": str(main),
        "license": lic,
        "attribution": f"{name} by {author}, BlenderKit ({lic.split(':')[0]})",
        "blender_python": code,
    }
