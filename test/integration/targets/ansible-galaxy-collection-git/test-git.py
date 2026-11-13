# Copyright: (c) 2026, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import json
import os
import shutil
import subprocess
import tempfile
import unittest

import yaml


class GitCollections(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='galaxy-git-')
        self.repository = os.path.join(self.work, 'repository')
        self.local_tmp = os.path.join(self.work, 'tmp')
        self.install_path = os.path.join(self.work, 'installed')
        os.mkdir(self.repository)
        os.mkdir(self.local_tmp)
        self.environment = dict(os.environ, ANSIBLE_LOCAL_TEMP=self.local_tmp, ANSIBLE_DEVEL_WARNING='False',
                                ANSIBLE_COLLECTIONS_PATHS=self.install_path, ANSIBLE_GALAXY_SERVER='http://127.0.0.1:1/')
        self.git('init')
        self.git('symbolic-ref', 'HEAD', 'refs/heads/main')
        self.git('config', 'user.name', 'Integration Tester')
        self.git('config', 'user.email', 'tester@example.org')
        self.collection('', 'root', 'initial')
        self.commit('initial')
        self.initial = self.git('rev-parse', 'HEAD').strip()
        self.url = 'git+file://' + self.repository

    def tearDown(self):
        shutil.rmtree(self.work)

    def write(self, path, content):
        with open(path, 'w') as stream:
            stream.write(content)

    def run_command(self, arguments, cwd=None, success=True):
        process = subprocess.Popen(arguments, cwd=cwd or self.work, env=self.environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout = process.communicate()[0].decode('utf-8')
        if success:
            self.assertEqual(process.returncode, 0, stdout)
        else:
            self.assertNotEqual(process.returncode, 0, stdout)
        return stdout

    def git(self, *arguments):
        return self.run_command(['git', '-C', self.repository] + list(arguments))

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-m', message)

    def collection(self, directory, name, content, dependencies=None):
        path = os.path.join(self.repository, directory)
        if not os.path.isdir(path):
            os.makedirs(path)
        metadata = {'namespace': 'testing', 'name': name, 'version': '1.2.3', 'readme': 'README.md',
                    'authors': ['Tester'], 'dependencies': dependencies or {}}
        self.write(os.path.join(path, 'galaxy.yml'), yaml.safe_dump(metadata))
        self.write(os.path.join(path, 'README.md'), content)

    def galaxy(self, action, *arguments, **kwargs):
        output = self.run_command(['ansible-galaxy', 'collection', action] + list(arguments), **kwargs)
        self.assertEqual(os.listdir(self.local_tmp), [], output)
        return output

    def install(self, source, content, name='root', extra=None):
        self.galaxy('install', source, '-p', self.install_path, '--force', *(extra or []))
        installed = os.path.join(self.install_path, 'ansible_collections', 'testing', name)
        with open(os.path.join(installed, 'README.md')) as stream:
            self.assertEqual(stream.read(), content)
        with open(os.path.join(installed, 'MANIFEST.json')) as stream:
            self.assertEqual(json.load(stream)['collection_info']['version'], '1.2.3')

    def test_revisions_and_installed_content(self):
        self.git('tag', 'release')
        self.write(os.path.join(self.repository, 'README.md'), 'main')
        self.commit('main')
        self.git('checkout', '-b', 'topic')
        self.write(os.path.join(self.repository, 'README.md'), 'topic')
        self.commit('topic')
        self.git('checkout', 'main')
        for suffix, content in [('', 'main'), (',main', 'main'), (',topic', 'topic'),
                                (',release', 'initial'), (',' + self.initial, 'initial')]:
            self.install(self.url + suffix, content)
        self.assertIn('Skipping', self.galaxy('install', self.url + ',topic', '-p', self.install_path))

    def test_root_selection_and_requirements_identity(self):
        self.collection('child', 'child', 'child')
        self.commit('child')
        self.install(self.url, 'initial')
        self.assertFalse(os.path.exists(os.path.join(self.install_path, 'ansible_collections', 'testing', 'child')))
        requirements = os.path.join(self.work, 'requirements.yml')
        self.write(requirements, yaml.safe_dump({'collections': [{'name': 'testing.child', 'src': self.url + '#/child',
                                                                 'scm': 'git', 'version': 'main'}]}))
        self.galaxy('install', '-r', requirements, '-p', self.install_path)
        with open(os.path.join(self.install_path, 'ansible_collections', 'testing', 'child', 'README.md')) as stream:
            self.assertEqual(stream.read(), 'child')

    def test_relative_treeishes_install_and_download(self):
        for content in ['middle', 'latest']:
            self.write(os.path.join(self.repository, 'README.md'), content)
            self.commit(content)
        for revision in ['HEAD~1', 'HEAD^', 'main~1']:
            self.install(self.url + ',' + revision, 'middle')
        download = os.path.join(self.work, 'download')
        self.galaxy('download', self.url + ',HEAD~1', '-p', download)
        self.galaxy('install', '-r', 'requirements.yml', '-p', self.install_path, '--force', cwd=download)
        with open(os.path.join(self.install_path, 'ansible_collections', 'testing', 'root', 'README.md')) as stream:
            self.assertEqual(stream.read(), 'middle')

    def test_invalid_metadata_identities(self):
        for field, value in [('name', 'root:bad'), ('namespace', 'testing:bad'),
                             ('dependencies', {'testing.other:bad': '*'})]:
            self.collection('', 'root', 'initial')
            path = os.path.join(self.repository, 'galaxy.yml')
            with open(path) as stream:
                metadata = yaml.safe_load(stream)
            metadata[field] = value
            self.write(path, yaml.safe_dump(metadata))
            self.commit('invalid identity ' + field)
            self.assertIn('Invalid collection name', self.galaxy('install', self.url, '-p', self.install_path, success=False))
            self.assertFalse(os.path.exists(os.path.join(self.install_path, 'ansible_collections', 'testing', 'root:bad')))

    def test_siblings_deep_fragments_dependencies_and_offline_download(self):
        os.unlink(os.path.join(self.repository, 'galaxy.yml'))
        self.collection('alpha', 'alpha', 'alpha', {'testing.zeta': '>=1.0.0'})
        self.collection('zeta', 'zeta', 'zeta', {'testing.alpha': '*'})
        self.collection('deep/parent/child', 'deep', 'deep')
        self.commit('siblings')
        self.install(self.url, 'alpha', name='alpha')
        self.install(self.url + '#/zeta', 'zeta', name='zeta', extra=['--no-deps'])
        self.install(self.url + '#deep/parent', 'deep', name='deep')
        self.install(self.url + '#alpha', 'alpha', name='alpha', extra=['--no-deps'])
        download = os.path.join(self.work, 'download')
        self.galaxy('download', self.url, '-p', download)
        with open(os.path.join(download, 'requirements.yml')) as stream:
            requirements = yaml.safe_load(stream)['collections']
        self.assertEqual(len(requirements), 2)
        self.assertTrue(all(entry['version'] == '1.2.3' for entry in requirements))
        self.galaxy('install', '-r', 'requirements.yml', '-p', os.path.join(self.work, 'offline'), cwd=download)
        with open(os.path.join(self.work, 'offline', 'ansible_collections', 'testing', 'alpha', 'README.md')) as stream:
            self.assertEqual(stream.read(), 'alpha')

    def test_failures_cleanup_and_verify(self):
        for suffix in [',missing', ',*', '#missing', '#../outside']:
            self.galaxy('install', self.url + suffix, '-p', self.install_path, success=False)
        self.assertIn('does not support Git', self.galaxy('verify', self.url, success=False))
        self.write(os.path.join(self.repository, 'galaxy.yml'), '[]')
        self.write(os.path.join(self.repository, 'MANIFEST.json'), '{}')
        self.commit('bad metadata')
        self.assertIn('mapping', self.galaxy('install', self.url, '-p', self.install_path, success=False))

    def test_symlink_escape_and_cycle(self):
        for target in ['../../outside', '/etc/passwd', '.']:
            link = os.path.join(self.repository, 'link')
            os.symlink(target, link)
            self.commit('symlink ' + target)
            self.galaxy('install', self.url, '-p', self.install_path, success=False)
            os.unlink(link)
            self.commit('remove symlink')


if __name__ == '__main__':
    unittest.main(verbosity=2)
