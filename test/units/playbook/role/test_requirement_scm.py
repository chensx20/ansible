# Copyright: (c) 2026, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import os
import tarfile

import pytest

from ansible import constants as C
from ansible.errors import AnsibleError
from ansible.galaxy import scm
from ansible.playbook.role.requirement import RoleRequirement
from units.compat.mock import MagicMock, patch


@pytest.mark.parametrize('repository', ['ssh://git@example.org/group/repo', 'git@example.org:group/repo.git',
                                        'https://user:secret@example.org/repo.git'])
@pytest.mark.parametrize('engine,version,keep', [
    ('git', 'topic', False), ('git', '', False), ('hg', 'tag', False), ('git', 'HEAD', True),
])
def test_archive_commands_and_cleanup(tmp_path, monkeypatch, repository, engine, version, keep):
    monkeypatch.setattr(C, 'DEFAULT_LOCAL_TMP', str(tmp_path))
    commands = []

    def process(command, cwd, stdout, stderr):
        commands.append(command)
        if command[1] == 'clone':
            os.mkdir(os.path.join(cwd, 'role'))
        child = MagicMock()
        child.communicate.return_value = (b'', b'')
        child.returncode = 0
        return child

    with patch.object(scm, 'get_bin_path', return_value='/usr/bin/' + engine), patch.object(scm, 'Popen', side_effect=process):
        archive = RoleRequirement.scm_archive_role(repository, scm=engine, name='role', version=version, keep_scm_meta=keep)
    assert commands[0] == ['/usr/bin/' + engine, 'clone', repository, 'role']
    assert list(tmp_path.iterdir()) == [tmp_path / os.path.basename(archive)]
    if keep:
        with tarfile.open(archive) as tar:
            assert tar.getnames() == ['role']
    elif engine == 'git':
        assert commands[-1] == ['/usr/bin/git', 'archive', '--prefix=role/', '--output=' + archive, version or 'HEAD']
        if version:
            assert commands[1] == ['/usr/bin/git', 'checkout', version, '--']
    else:
        assert commands[-1] == ['/usr/bin/hg', 'archive', '--prefix', 'role/', '-r', version, archive]
    os.unlink(archive)


@pytest.mark.parametrize('failed_command', ['clone', 'checkout', 'archive'])
def test_archive_failure_redacts_credentials_and_cleans(tmp_path, monkeypatch, failed_command):
    monkeypatch.setattr(C, 'DEFAULT_LOCAL_TMP', str(tmp_path))
    repository = 'https://user:secret@example.org/repo.git'
    commands = []

    def process(command, cwd, stdout, stderr):
        commands.append(command)
        if command[1] == 'clone':
            os.mkdir(os.path.join(cwd, 'role'))
        child = MagicMock()
        child.communicate.return_value = (b'', repository.encode('ascii'))
        child.returncode = int(command[1] == failed_command)
        return child

    with patch.object(scm, 'get_bin_path', return_value='/usr/bin/git'), patch.object(scm, 'Popen', side_effect=process):
        with pytest.raises(AnsibleError) as error:
            RoleRequirement.scm_archive_role(repository, name='role', version='missing')
    assert 'secret' not in str(error.value)
    assert 'user' not in str(error.value)
    assert list(tmp_path.iterdir()) == []
    assert commands[-1][1] == failed_command
