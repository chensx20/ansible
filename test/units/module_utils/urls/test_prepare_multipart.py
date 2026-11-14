# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function
__metaclass__ = type

import email

import pytest

from ansible.module_utils._text import to_bytes
from ansible.module_utils.six import PY3
from ansible.module_utils.urls import prepare_multipart


def parse(fields):
    content_type, body = prepare_multipart(fields)
    raw = to_bytes('Content-Type: ' + content_type + '\r\n\r\n') + body
    message = email.message_from_string(raw.decode('latin-1') if PY3 else raw)
    assert body.endswith(b'--\r\n')
    assert b'\r\n\r\n' in body
    return message.get_payload()


def test_text_and_inline_file():
    parts = parse({'text': u'caf\u00e9', 'file': {'filename': 'dir/a"b.txt', 'content': 'hello'}})
    parts = dict((part.get_param('name', header='content-disposition'), part) for part in parts)
    assert parts['text'].get_content_type() == 'text/plain'
    assert parts['file'].get_filename() == 'a"b.txt'
    assert parts['file'].get_payload() == 'hello'


def test_binary_file(tmpdir):
    source = tmpdir.join('upload.unknown-extension')
    source.write_binary(b'\x00\xff\r\nhello')
    content_type, body = prepare_multipart({'file': {'filename': str(source)}})
    assert b'\x00\xff\r\nhello' in body
    assert b'Content-Type: application/octet-stream' in body
    assert b'filename="upload.unknown-extension"' in body
    assert content_type.startswith('multipart/form-data; boundary=')


def test_source_and_metadata(tmpdir):
    source = tmpdir.join('multipart-0')
    source.write_binary(b'file content')
    part = parse({'file': {'src': str(source), 'filename': 'original.json'}})[0]
    assert part.get_filename() == 'original.json'
    assert part.get_content_type() == 'application/json'
    assert part.get_payload() == 'file content'


def test_unicode_metadata():
    part = parse({u'caf\u00e9': {'filename': u'caf\u00e9.txt', 'content': 'hello'}})[0]
    assert part.get_filename().encode('utf-8') == u'caf\u00e9.txt'.encode('utf-8')


def test_explicit_mime():
    part = parse({'file': {'content': 'hello', 'mime_type': 'application/custom'}})[0]
    assert part.get_content_type() == 'application/custom'


@pytest.mark.parametrize('fields', [[], {'a': 1}, {'a': {}}, {'a': {'content': None}},
                                    {'a': {'filename': 3}}, {'a': {'mime_type': 'invalid', 'content': ''}},
                                    {'a\r\nInjected: yes': ''}, {'a': {'filename': 'bad\nname', 'content': ''}},
                                    {'a': {'src': 'path', 'content': ''}}])
def test_invalid_fields(fields):
    with pytest.raises((TypeError, ValueError)):
        prepare_multipart(fields)


def test_missing_file(tmpdir):
    with pytest.raises(IOError):
        prepare_multipart({'file': {'filename': str(tmpdir.join('absent'))}})


def test_empty_body_and_unique_boundaries():
    content_type, body = prepare_multipart({})
    boundary = content_type.split('boundary=')[1]
    assert body == to_bytes('--' + boundary + '--\r\n')
    assert prepare_multipart({})[0] != content_type
