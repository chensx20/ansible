# Copyright: (c) 2026, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import re
from collections import namedtuple

from ansible.errors import AnsibleError
from ansible.module_utils.six import string_types
from ansible.module_utils.six.moves.urllib.parse import urlsplit
from ansible.utils.collection_loader import AnsibleCollectionRef


GitCollectionSource = namedtuple('GitCollectionSource', ['repository', 'revision', 'path', 'collection'])


def is_git_url(value):
    if not isinstance(value, string_types):
        return False
    repository = value.split(',', 1)[0].split('#', 1)[0]
    return (repository.startswith(('git+', 'ssh://', 'git://')) or
            re.match(r'^[^/@:]+@[^/:]+:', repository) is not None or
            (urlsplit(repository).scheme in ('http', 'https') and urlsplit(repository).path.endswith('.git')))


def parse_collection_source(entry):
    """Normalize a boundary requirement to the existing (name, version, source) contract."""
    if isinstance(entry, string_types):
        entry = {'name': entry}
    if not isinstance(entry, dict):
        raise AnsibleError('Collection requirement must be a string or mapping.')
    name = entry.get('src', entry.get('name'))
    if not isinstance(name, string_types) or not name:
        raise AnsibleError('Collections requirement entry should contain the key name.')
    for key in ('version', 'source', 'scm', 'type', 'name', 'src'):
        if key in entry and not isinstance(entry[key], string_types):
            raise AnsibleError('Collection requirement %s must be a string.' % key)
    scm = entry.get('scm')
    source_type = entry.get('type')
    if scm not in (None, 'git') or source_type not in (None, 'git', 'galaxy'):
        raise AnsibleError('Unsupported collection SCM or type; only Git SCM is supported.')
    git = is_git_url(name) or scm == 'git' or source_type == 'git'
    if not git:
        if 'src' in entry:
            raise AnsibleError('Collection src requires a Git repository.')
        return name, entry.get('version', '*'), entry.get('source')
    if source_type == 'galaxy' or 'source' in entry:
        raise AnsibleError('Git collection requirements cannot specify a Galaxy source or type.')
    asserted_name = entry.get('name') if 'src' in entry else None
    if asserted_name and not AnsibleCollectionRef.is_valid_collection_name(asserted_name):
        raise AnsibleError('Collection name with src must be a valid namespace.name identity.')
    repository, comma, compact_revision = name.partition(',')
    if comma and not compact_revision:
        raise AnsibleError('Git collection revision must not be empty.')
    revision = entry.get('version', compact_revision if comma else 'HEAD')
    if not revision or revision.startswith('-') or (comma and revision != compact_revision):
        raise AnsibleError('Git collection revisions must be non-empty and must not conflict.')
    repository, fragment, path = repository.partition('#')
    if repository.startswith('git+'):
        repository = repository[4:]
    if not repository or repository.startswith('-'):
        raise AnsibleError('Git collection repository must not be empty or an option.')
    path = path.lstrip('/')
    if chr(92) in path or '..' in path.split('/') or chr(0) in path:
        raise AnsibleError('Git collection directory must be repository-relative without traversal.')
    source = GitCollectionSource(repository, revision, path, asserted_name)
    return name, revision, source
