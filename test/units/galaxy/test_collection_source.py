# Copyright: (c) 2026, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

from ansible.errors import AnsibleError
from ansible.galaxy.collection_source import GitCollectionSource, is_git_url, parse_collection_source


@pytest.mark.parametrize('url', [
    'git+file:///tmp/repo', 'git+https://example.org/repo', 'ssh://git@example.org/repo',
    'git@example.org:group/repo.git#/nested,branch', 'https://example.org/repo.git',
    'http://example.org/repo.git#collection,tag',
    'example.org:team/repo.git#/nested,branch', 'example.org:repo.git',
    'example.org:team/repo', 'git@example.org:repo',
])
def test_detect_git(url):
    assert is_git_url(url)


@pytest.mark.parametrize('url', ['ns.collection', 'ns.collection:1.2.3', 'ns.collection:>=1.0.0,<2.0.0',
                                 'https://example.org/artifact.tar.gz', 'http://example.org/artifact.tar.gz', '/tmp/artifact.tar.gz'])
def test_preserve_non_git(url):
    assert not is_git_url(url)
    assert parse_collection_source(url) == (url, '*', None)


@pytest.mark.parametrize('entry,expected', [
    ('git+file:///tmp/repo', GitCollectionSource('file:///tmp/repo', 'HEAD', '', None)),
    ('git@example.org:repo#/nested,topic', GitCollectionSource('git@example.org:repo', 'topic', 'nested', None)),
    ('example.org:team/repo.git#/nested,topic', GitCollectionSource('example.org:team/repo.git', 'topic', 'nested', None)),
    ({'name': 'example.org:repo.git'}, GitCollectionSource('example.org:repo.git', 'HEAD', '', None)),
    ({'name': 'https://example.org/repo.git', 'version': '*'},
     GitCollectionSource('https://example.org/repo.git', '*', '', None)),
    ({'name': 'ns.collection', 'src': 'https://example.org/repo', 'scm': 'git', 'version': 'tag'},
     GitCollectionSource('https://example.org/repo', 'tag', '', 'ns.collection')),
    ({'name': 'https://example.org/repo#parent/child,tag', 'type': 'git', 'version': 'tag'},
     GitCollectionSource('https://example.org/repo', 'tag', 'parent/child', None)),
])
def test_normalize_git(entry, expected):
    assert parse_collection_source(entry)[2] == expected


@pytest.mark.parametrize('entry', [
    {'name': 'git+file:///repo', 'source': 'https://galaxy.example.org'},
    {'name': 'git+file:///repo', 'type': 'galaxy'},
    {'name': 'git+file:///repo', 'scm': 'hg'},
    {'name': 'git+file:///repo', 'type': 'tar'},
    {'name': 'git+file:///repo,one', 'version': 'two'},
    {'name': 'git+file:///repo', 'version': 123},
    {'name': 'git+file:///repo', 'version': ''},
    {'name': 'git+file:///repo', 'version': '--help'},
    {'name': 'bad-name', 'src': 'git+file:///repo'},
    {'src': 'https://example.org/artifact.tar.gz'},
    'git+file:///repo#../outside', 'git+file:///repo#nested/../../outside',
    'git+file:///repo#nested' + chr(92) + 'outside', 'git+file:///repo,', None, [],
])
def test_invalid_git_requirement(entry):
    with pytest.raises(AnsibleError):
        parse_collection_source(entry)
