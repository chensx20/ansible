# -*- coding: utf-8 -*-
# (c) 2015, Brian Coca  <briancoca+dev@gmail.com>
# (c) 2018, Matt Martz  <matt@sivel.net>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# Make coding more python3-ish
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import copy
import os

from ansible.errors import AnsibleError, AnsibleAction, _AnsibleActionDone, AnsibleActionFail
from ansible.module_utils._text import to_native
from ansible.module_utils.common._collections_compat import Mapping
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.module_utils.six import string_types
from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):

    TRANSFERS_FILES = True

    def run(self, tmp=None, task_vars=None):
        self._supports_async = True

        if task_vars is None:
            task_vars = dict()

        result = super(ActionModule, self).run(tmp, task_vars)
        del tmp  # tmp no longer has any effect

        src = self._task.args.get('src', None)
        remote_src = boolean(self._task.args.get('remote_src', 'no'), strict=False)

        try:
            if self._task.args.get('body_format') == 'form-multipart' and not remote_src:
                new_module_args = copy.deepcopy(self._task.args)
                body = new_module_args.get('body')
                if not isinstance(body, Mapping):
                    raise AnsibleActionFail('multipart body must be a mapping')
                for index, field in enumerate(body.values()):
                    if not isinstance(field, Mapping) or 'content' in field:
                        continue
                    filename = field.get('src') or field.get('filename')
                    if not filename:
                        continue
                    if not isinstance(filename, string_types):
                        raise AnsibleActionFail('multipart file paths must be strings')
                    try:
                        local_src = self._find_needle('files', filename)
                    except AnsibleError as e:
                        raise AnsibleActionFail(to_native(e))
                    tmp_src = self._connection._shell.join_path(self._connection._shell.tmpdir, 'multipart-%s' % index)
                    self._transfer_file(local_src, tmp_src)
                    self._fixup_perms2((self._connection._shell.tmpdir, tmp_src))
                    field['filename'] = field.get('filename') or filename
                    field['src'] = tmp_src
                raise _AnsibleActionDone(result=self._execute_module(
                    'uri', module_args=new_module_args, task_vars=task_vars, wrap_async=self._task.async_val))
            if (src and remote_src) or not src:
                # everything is remote, so we just execute the module
                # without changing any of the module arguments
                raise _AnsibleActionDone(result=self._execute_module(task_vars=task_vars, wrap_async=self._task.async_val))

            try:
                src = self._find_needle('files', src)
            except AnsibleError as e:
                raise AnsibleActionFail(to_native(e))

            tmp_src = self._connection._shell.join_path(self._connection._shell.tmpdir, os.path.basename(src))
            self._transfer_file(src, tmp_src)
            self._fixup_perms2((self._connection._shell.tmpdir, tmp_src))

            new_module_args = self._task.args.copy()
            new_module_args.update(
                dict(
                    src=tmp_src,
                )
            )

            result.update(self._execute_module('uri', module_args=new_module_args, task_vars=task_vars, wrap_async=self._task.async_val))
        except AnsibleAction as e:
            result.update(e.result)
        finally:
            if not self._task.async_val:
                self._remove_tmp_path(self._connection._shell.tmpdir)
        return result
