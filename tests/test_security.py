import io
import socket
import zipfile

import pytest

from blender_assets_mcp import ambientcg, blenderkit, common


def addresses(ip):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))]


def test_network_policy_rejects_unsafe_urls_and_private_dns(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: addresses('8.8.8.8'))
    common.validate_url('https://api.polyhaven.com/assets')
    for url in ['http://api.polyhaven.com/', 'https://api.polyhaven.com.evil.test/',
                'https://user@api.polyhaven.com/', 'https://api.polyhaven.com:444/',
                'https://127.0.0.1/']:
        with pytest.raises(ValueError):
            common.validate_url(url)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: addresses('127.0.0.1'))
    with pytest.raises(ValueError):
        common.validate_url('https://api.polyhaven.com/')


def test_redirects_are_validated(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: addresses('8.8.8.8'))
    request = common.urllib.request.Request('https://api.polyhaven.com/')
    with pytest.raises(ValueError):
        common.RestrictedRedirect().redirect_request(request, None, 302, '', {}, 'https://evil.test/')


def test_download_limit_and_temporary_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(common, 'MAX_DOWNLOAD_BYTES', 3)
    monkeypatch.setattr(common, 'open_url', lambda *a: io.BytesIO(b'1234'))
    with pytest.raises(ValueError):
        common.download('https://unused', tmp_path / 'file')
    assert list(tmp_path.iterdir()) == []


def test_zip_expansion_limit_and_traversal(tmp_path):
    archive = tmp_path / 'asset.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('bomb', b'0' * (2 * 1024 * 1024))
    with pytest.raises(ValueError, match='resource limits'):
        ambientcg.extract(archive, tmp_path / 'out')


def test_cache_rejects_symlink_escape(tmp_path, monkeypatch):
    root = tmp_path / 'cache'
    root.mkdir()
    (root / 'polyhaven').symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setenv('BLENDER_ASSETS_CACHE', str(root))
    with pytest.raises(ValueError):
        common.asset_dir('polyhaven', 'asset', '1k')


def test_blenderkit_identity_and_license(monkeypatch):
    asset = {'assetBaseId': 'wrong', 'license': 'cc_zero', 'isFree': True}
    monkeypatch.setattr(blenderkit, 'query', lambda *args: [asset])
    with pytest.raises(ValueError, match='identity'):
        blenderkit.fetch('wanted', '1k')
    asset.update(assetBaseId='wanted', license='unknown')
    with pytest.raises(ValueError, match='license'):
        blenderkit.fetch('wanted', '1k')


def test_blenderkit_marker_cannot_escape(isolated_cache, monkeypatch):
    root = common.asset_dir('blenderkit', 'wanted', '1k')
    root.mkdir(parents=True)
    (root / '.complete').write_text('../../escape')
    asset = {'assetBaseId': 'wanted', 'license': 'cc_zero', 'isFree': True,
             'assetType': 'model', 'files': [{'fileType': 'blend', 'downloadUrl': 'unused'}]}
    monkeypatch.setattr(blenderkit, 'query', lambda *args: [asset])
    with pytest.raises(ValueError, match='invalid or incomplete'):
        blenderkit.fetch('wanted', '1k')
