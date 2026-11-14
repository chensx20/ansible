# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function
__metaclass__ = type

import os

import pytest

from ansible.plugins.action import ActionBase
from ansible.plugins.action.uri import ActionModule
from units.compat.mock import MagicMock


@pytest.mark.parametrize('remote_src', [True, False])
@pytest.mark.parametrize('async_val', [0, 30])
def test_multipart_transfer(mocker, remote_src, async_val):
    mocker.patch.object(ActionBase, 'run', return_value={})
    task = MagicMock()
    task.async_val = async_val
    task.args = {'body_format': 'form-multipart', 'remote_src': remote_src, 'body': {
        'one': {'filename': '/one/file.txt'}, 'two': {'filename': '/two/file.txt'},
        'inline': {'filename': 'inline.txt', 'content': 'inline'}, 'text': 'value',
    }}
    connection = MagicMock()
    connection._shell.tmpdir = '/tmp/ansible'
    connection._shell.join_path.side_effect = os.path.join
    action = ActionModule(task, connection, MagicMock(), None, None, None)
    action._find_needle = MagicMock(side_effect=lambda directory, path: path)
    action._transfer_file = MagicMock()
    action._fixup_perms2 = MagicMock()
    action._remove_tmp_path = MagicMock()
    action._execute_module = MagicMock(return_value={'ok': True})

    assert action.run(task_vars={})['ok'] is True
    assert action._transfer_file.call_count == (0 if remote_src else 2)
    assert action._remove_tmp_path.call_count == (0 if async_val else 1)
    assert 'src' not in task.args['body']['one']
    assert 'src' not in task.args['body']['two']
    if not remote_src:
        body = action._execute_module.call_args[1]['module_args']['body']
        assert body['one']['src'] != body['two']['src']
        assert body['one']['filename'] == '/one/file.txt'
        assert body['two']['filename'] == '/two/file.txt'
        assert body['inline'] == task.args['body']['inline']
