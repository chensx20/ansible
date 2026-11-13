# Copyright: (c) 2026, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import os
import re
import shutil
import tarfile
import tempfile
from subprocess import Popen, PIPE

from ansible import constants as C
from ansible.errors import AnsibleError
from ansible.module_utils._text import to_native, to_text
from ansible.module_utils.common.process import get_bin_path


def _redact(value):
    return re.sub(r'(https?://)[^/@\s]+@', r'\1***@', to_text(value))


def scm_archive_resource(src, scm='git', name=None, version='HEAD', keep_scm_meta=False):
    """Archive a complete SCM checkout; callers own the returned temporary archive."""
    if scm not in ('git', 'hg'):
        raise AnsibleError('- scm %s is not currently supported' % scm)
    try:
        executable = get_bin_path(scm)
    except (ValueError, OSError, IOError):
        raise AnsibleError('could not find/use %s, it is required to continue with installing %s' % (scm, _redact(src)))

    def run(command, cwd):
        try:
            process = Popen(command, cwd=cwd, stdout=PIPE, stderr=PIPE)
            stdout, stderr = process.communicate()
        except OSError as err:
            raise AnsibleError('when executing %s: %s' % (_redact(' '.join(command)), _redact(to_native(err))))
        if process.returncode:
            raise AnsibleError('- command %s failed (rc=%s) - %s' %
                               (_redact(' '.join(command)), process.returncode, _redact(to_native(stderr))))

    tempdir = tempfile.mkdtemp(dir=C.DEFAULT_LOCAL_TMP)
    archive = None
    try:
        run([executable, 'clone', src, name], tempdir)
        checkout = os.path.join(tempdir, name)
        if scm == 'git' and version:
            run([executable, 'checkout', to_text(version), '--'], checkout)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar', dir=C.DEFAULT_LOCAL_TMP) as output:
            archive = output.name
        if keep_scm_meta:
            with tarfile.open(archive, 'w') as tar:
                tar.add(checkout, arcname=name)
        elif scm == 'hg':
            command = [executable, 'archive', '--prefix', '%s/' % name]
            if version:
                command.extend(['-r', version])
            run(command + [archive], checkout)
        else:
            run([executable, 'archive', '--prefix=%s/' % name, '--output=%s' % archive, 'HEAD'], checkout)
        result = archive
        archive = None
        return result
    finally:
        shutil.rmtree(tempdir)
        if archive is not None:
            os.unlink(archive)
