# Copyright: (c) 2026, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import json
import os
import subprocess
import tarfile

import pytest
import yaml

from ansible import constants as C
from ansible.errors import AnsibleError
from ansible.galaxy import collection
from ansible.galaxy.collection_source import parse_collection_source
from ansible.module_utils._text import to_bytes


def git(repository, *arguments):
    return subprocess.check_output(['git', '-C', str(repository)] + list(arguments)).decode('utf-8').strip()


def write_collection(path, name='example', version='1.2.3', dependencies=None):
    path.mkdir(parents=True, exist_ok=True)
    metadata = {'namespace': 'testing', 'name': name, 'version': version, 'readme': 'README.md',
                'authors': ['Tester'], 'dependencies': dependencies or {}}
    (path / 'galaxy.yml').write_text(yaml.safe_dump(metadata), encoding='utf-8')
    (path / 'README.md').write_text('collection content', encoding='utf-8')
    return metadata


@pytest.fixture
def repository(tmp_path, monkeypatch):
    local_tmp = tmp_path / 'local'
    local_tmp.mkdir()
    monkeypatch.setattr(C, 'DEFAULT_LOCAL_TMP', str(local_tmp))
    root = tmp_path / 'repository'
    root.mkdir()
    git(root, 'init')
    git(root, 'symbolic-ref', 'HEAD', 'refs/heads/main')
    git(root, 'config', 'user.email', 'tester@example.org')
    git(root, 'config', 'user.name', 'Tester')
    write_collection(root)
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'initial')
    return root


def requirement(repository, suffix='', **kwargs):
    return parse_collection_source(dict({'name': 'git+file://' + str(repository) + suffix}, **kwargs))


def resolve(repository, tmp_path, suffix='', existing=None, force=False, no_deps=False, entries=None, force_deps=False):
    output = tmp_path / 'output'
    output.mkdir(exist_ok=True)
    return collection._build_dependency_map(entries or [requirement(repository, suffix)], existing or [],
                                            to_bytes(str(output)), [], True, force, force_deps, no_deps)


@pytest.mark.parametrize('revision', ['HEAD', 'main', 'release', 'old', 'topic'])
def test_full_history_revisions(repository, tmp_path, revision):
    old = git(repository, 'rev-parse', 'HEAD')
    git(repository, 'tag', 'release')
    (repository / 'README.md').write_text('main content', encoding='utf-8')
    git(repository, 'commit', '-am', 'main')
    git(repository, 'checkout', '-b', 'topic')
    (repository / 'README.md').write_text('topic content', encoding='utf-8')
    git(repository, 'commit', '-am', 'topic')
    git(repository, 'checkout', 'main')
    selected = old if revision == 'old' else revision
    requirements = resolve(repository, tmp_path, ',' + selected)
    req = requirements['testing.example']
    assert req.latest_version == '1.2.3'
    expected = 'collection content' if revision in ('old', 'release') else ('topic content' if revision == 'topic' else 'main content')
    with tarfile.open(req.b_path) as tar:
        assert tar.extractfile('README.md').read().decode('utf-8') == expected
    assert list((tmp_path / 'local').iterdir()) == []


def test_root_wins_over_children(repository, tmp_path):
    write_collection(repository / 'child', 'child')
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'child')
    assert list(resolve(repository, tmp_path)) == ['testing.example']


@pytest.mark.parametrize('fragment,identities', [
    ('', ['testing.alpha', 'testing.zeta']),
    ('#/zeta', ['testing.zeta']),
    ('#deep/parent', ['testing.deep']),
])
def test_discover_collections(repository, tmp_path, fragment, identities):
    (repository / 'galaxy.yml').unlink()
    write_collection(repository / 'zeta', 'zeta')
    write_collection(repository / 'alpha', 'alpha')
    write_collection(repository / 'deep' / 'parent' / 'nested', 'deep')
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'siblings')
    assert list(resolve(repository, tmp_path, fragment)) == identities


@pytest.mark.parametrize('metadata,error', [
    ([], 'must contain a mapping'),
    ({'namespace': 'testing'}, 'mandatory keys'),
    ({'version': 'branch'}, 'must be semantic'),
    ({'namespace': 'invalid-name'}, 'Invalid collection name'),
    ({'version': 1.2}, 'must be strings'),
    ({'readme': None}, 'must not be empty'),
    ({'authors': [123]}, 'must contain strings'),
    ({'dependencies': []}, 'must be a mapping'),
    ({'dependencies': {'invalid-name': '*'}}, 'Invalid collection name'),
    ({'dependencies': {'testing.other': 1}}, 'version strings'),
])
def test_invalid_selected_metadata(repository, tmp_path, metadata, error):
    if isinstance(metadata, dict) and metadata != {'namespace': 'testing'}:
        original = yaml.safe_load((repository / 'galaxy.yml').read_text(encoding='utf-8'))
        original.update(metadata)
        metadata = original
    (repository / 'galaxy.yml').write_text(yaml.safe_dump(metadata), encoding='utf-8')
    (repository / 'MANIFEST.json').write_text('{}', encoding='utf-8')
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'invalid metadata')
    with pytest.raises(AnsibleError, match=error):
        resolve(repository, tmp_path)
    assert list((tmp_path / 'local').iterdir()) == []


@pytest.mark.parametrize('suffix,error', [
    (',missing-revision', 'checkout'), (',*', 'checkout'),
    ('#absent', 'does not exist'), ('#empty', 'no collections'),
])
def test_invalid_revision_directory_and_cleanup(repository, tmp_path, suffix, error):
    (repository / 'empty').mkdir()
    (repository / 'empty' / 'file').write_text('empty', encoding='utf-8')
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'empty directory')
    with pytest.raises(AnsibleError, match=error):
        resolve(repository, tmp_path, suffix)
    assert list((tmp_path / 'local').iterdir()) == []


@pytest.mark.parametrize('target', ['../../outside', '/etc/passwd', '../collection-sibling/secret', '.'])
def test_reject_symlink_escape_and_cycles(repository, tmp_path, target):
    os.symlink(target, str(repository / 'link'))
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'symlink')
    with pytest.raises(AnsibleError, match='outside|cycle'):
        resolve(repository, tmp_path)
    assert list((tmp_path / 'local').iterdir()) == []


def test_metadata_identity_assertion(repository, tmp_path):
    entry = parse_collection_source({'name': 'testing.other', 'src': 'git+file://' + str(repository)})
    with pytest.raises(AnsibleError, match='requested identity'):
        resolve(repository, tmp_path, entries=[entry])


def test_stale_manifest_does_not_override_galaxy_metadata(repository, tmp_path):
    (repository / 'MANIFEST.json').write_text('{}', encoding='utf-8')
    (repository / 'FILES.json').write_text('{}', encoding='utf-8')
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'stale manifests')
    req = resolve(repository, tmp_path)['testing.example']
    with tarfile.open(req.b_path) as tar:
        assert tar.getnames().count('MANIFEST.json') == 1
        assert tar.getnames().count('FILES.json') == 1


def test_cross_linked_directory_cycle(repository, tmp_path):
    (repository / 'one').mkdir()
    (repository / 'two').mkdir()
    os.symlink('../two', str(repository / 'one' / 'link'))
    os.symlink('../one', str(repository / 'two' / 'link'))
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'cross-linked cycle')
    with pytest.raises(AnsibleError, match='cycle'):
        resolve(repository, tmp_path)


@pytest.mark.parametrize('name,kind,link', [
    ('collection/../../outside', tarfile.REGTYPE, ''),
    ('/tmp/outside', tarfile.REGTYPE, ''),
    ('collection/link', tarfile.SYMTYPE, '../../outside'),
    ('collection/link', tarfile.LNKTYPE, 'collection/file'),
    ('collection/device', tarfile.CHRTYPE, ''),
    ('collection/fifo', tarfile.FIFOTYPE, ''),
])
def test_unsafe_archive_members(repository, tmp_path, monkeypatch, name, kind, link):
    archive = tmp_path / 'unsafe.tar'
    with tarfile.open(str(archive), 'w') as tar:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = link
        tar.addfile(member)
    monkeypatch.setattr(collection, 'scm_archive_resource', lambda *args, **kwargs: str(archive))
    with pytest.raises(AnsibleError, match='outside|unsupported'):
        resolve(repository, tmp_path)
    assert not archive.exists()
    assert list((tmp_path / 'local').iterdir()) == []


def test_conflicting_git_revision(repository, tmp_path):
    git(repository, 'tag', 'release')
    with pytest.raises(AnsibleError, match='Conflicting collection sources'):
        resolve(repository, tmp_path, entries=[requirement(repository), requirement(repository, ',release')])


def test_dependencies_cycles_and_no_deps(repository, tmp_path):
    (repository / 'galaxy.yml').unlink()
    write_collection(repository / 'alpha', 'alpha', dependencies={'testing.zeta': '>=1.0.0'})
    write_collection(repository / 'zeta', 'zeta', dependencies={'testing.alpha': '*'})
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'dependencies')
    assert set(resolve(repository, tmp_path)) == {'testing.alpha', 'testing.zeta'}
    assert list(resolve(repository, tmp_path, '#alpha', no_deps=True)) == ['testing.alpha']


def test_installed_comparison_uses_metadata_not_treeish(repository, tmp_path):
    existing = collection.CollectionRequirement('testing', 'example', None, None, ['1.2.3'], '*', False, skip=True)
    assert resolve(repository, tmp_path, ',main', existing=[existing])['testing.example'] is existing
    assert not resolve(repository, tmp_path, ',main', existing=[existing], force=True)['testing.example'].skip
    assert not resolve(repository, tmp_path, ',main', existing=[existing], force_deps=True)['testing.example'].skip


def test_prerelease_and_download_reuses_artifact(repository, tmp_path):
    metadata = yaml.safe_load((repository / 'galaxy.yml').read_text(encoding='utf-8'))
    metadata['version'] = '2.0.0-beta.1'
    (repository / 'galaxy.yml').write_text(yaml.safe_dump(metadata), encoding='utf-8')
    git(repository, 'commit', '-am', 'prerelease')
    req = resolve(repository, tmp_path)['testing.example']
    assert req.latest_version == '2.0.0-beta.1'
    assert req.download(to_bytes(str(tmp_path))) == req.b_path.decode('utf-8')
    destination = tmp_path / 'installed'
    req.install(str(destination), to_bytes(str(tmp_path)))
    manifest = json.loads((destination / 'testing' / 'example' / 'MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['collection_info']['version'] == '2.0.0-beta.1'
