import io
import json
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from blender_assets_mcp import ambientcg, blenderkit, common, polyhaven


def test_cache_keys_distinguish_colliding_ids_and_sources():
    assert common.asset_dir('a/b', 'x', '1k') != common.asset_dir('a_b', 'x', '1k')
    assert common.asset_dir('source', 'a/b', '1k') != common.asset_dir('source', 'a_b', '1k')
    assert common.asset_dir('source', 'x', 'a/b') != common.asset_dir('source', 'x', 'a_b')


def test_failure_does_not_publish_partial_archive(monkeypatch):
    asset = {'assetId': 'brick', 'dataType': 'Material', 'downloadFolders': {'default': {
        'downloadFiletypeCategories': {'zip': {'downloads': [{'attribute': '1K-JPG', 'downloadLink': 'unused'}]}}}}}
    monkeypatch.setattr(ambientcg, 'query', lambda *_: [asset])

    def bad_download(_url, path):
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('.complete', 'forged')
            z.writestr('brick_Color.jpg', 'partial')
            z.writestr('../escape', 'bad')
        return path

    monkeypatch.setattr(ambientcg, 'download', bad_download)
    with pytest.raises(ValueError):
        ambientcg.fetch('brick', '1k')
    root = common.asset_dir('ambientcg', 'brick', '1k')
    assert not root.exists()
    assert not list(root.parent.glob('.asset-*'))
    with pytest.raises(ValueError):
        ambientcg.fetch('brick', '1k')


def test_cache_identity_license_and_missing_file_fail_closed():
    def populate(root):
        (root / 'file').write_text('asset')
        return 'file'

    meta = {'kind': 'model', 'license': 'cc_zero'}
    root, _ = common.cached_asset('blenderkit', 'id', '1k', meta, populate)
    with pytest.raises(ValueError, match='identity or license'):
        common.cached_asset('blenderkit', 'id', '1k', {**meta, 'license': 'royalty_free'}, populate)
    (root / 'file').unlink()
    with pytest.raises(ValueError, match='incomplete'):
        common.cached_asset('blenderkit', 'id', '1k', meta, populate)


def test_unlisted_file_is_rejected():
    def populate(root):
        (root / 'file').write_text('asset')
        return 'file'

    root, _ = common.cached_asset('source', 'id', '1k', {}, populate)
    (root / 'extra').write_text('unexpected')
    with pytest.raises(ValueError, match='contents changed'):
        common.cached_asset('source', 'id', '1k', {}, populate)


def test_polyhaven_failed_include_does_not_publish(monkeypatch):
    monkeypatch.setattr(polyhaven, 'catalog', lambda kind: {'id': {'name': 'asset'}} if kind == 'model' else {})
    monkeypatch.setattr(polyhaven, 'get_json', lambda *_: {'blend': {'1k': {'blend': {
        'url': 'https://example.test/main.blend', 'include': {'texture.png': {'url': 'unused'}}}}}})

    def fail_after_include(url, dest):
        if url == 'unused':
            dest.write_bytes(b'partial')
            return dest
        raise OSError('download interrupted')

    monkeypatch.setattr(polyhaven, 'download', fail_after_include)
    with pytest.raises(OSError, match='interrupted'):
        polyhaven.fetch('id', '1k')
    assert not common.asset_dir('polyhaven', 'id', '1k').exists()


def test_blenderkit_changed_license_is_not_applied_to_cached_file(monkeypatch):
    asset = {'assetBaseId': 'id', 'license': 'cc_zero', 'isFree': True, 'assetType': 'model',
             'files': [{'fileType': 'blend', 'downloadUrl': 'unused'}]}
    monkeypatch.setattr(blenderkit, 'query', lambda *_: [asset])
    monkeypatch.setattr(blenderkit, 'get_json', lambda *_: {'filePath': 'https://example.test/a.blend'})
    monkeypatch.setattr(blenderkit, 'download', lambda _url, dest: (dest.write_bytes(b'asset'), dest)[1])
    assert blenderkit.fetch('id', 'original')['license'] == common.CC0
    asset['license'] = 'royalty_free'
    with pytest.raises(ValueError, match='identity or license'):
        blenderkit.fetch('id', 'original')


def test_concurrent_publication_leaves_one_complete_entry():
    barrier = threading.Barrier(2)

    def populate(root):
        (root / 'file').write_text('asset')
        barrier.wait(timeout=5)
        return 'file'

    def fetch():
        return common.cached_asset('source', 'id', '1k', {'license': 'cc0'}, populate)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: fetch(), range(2)))
    assert results[0] == results[1]
    root, name = results[0]
    assert (root / name).read_text() == 'asset'
    assert json.loads((root.parent / 'manifest.json').read_text())['identity']['id'] == 'id'
    assert not list(root.parent.parent.glob('.asset-*'))


def test_short_content_length_is_not_published(tmp_path, monkeypatch):
    class ShortResponse(io.BytesIO):
        headers = {'Content-Length': '10'}

    monkeypatch.setattr(common, 'open_url', lambda *_: ShortResponse(b'short'))
    with pytest.raises(ValueError, match='incomplete'):
        common.download('unused', tmp_path / 'file')
    assert not list(tmp_path.iterdir())
