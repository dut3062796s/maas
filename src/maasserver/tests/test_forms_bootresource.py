# Copyright 2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `BootSourceForm`."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []

from datetime import datetime
import random

from django.core.files.uploadedfile import SimpleUploadedFile
from maasserver import forms
from maasserver.enum import (
    BOOT_RESOURCE_FILE_TYPE,
    BOOT_RESOURCE_TYPE,
    )
from maasserver.forms import BootResourceForm
from maasserver.models import BootResource
from maasserver.testing.architecture import make_usable_architecture
from maasserver.testing.factory import factory
from maasserver.testing.orm import reload_object
from maasserver.testing.testcase import MAASServerTestCase


class TestBootResourceForm(MAASServerTestCase):

    def pick_filetype(self):
        return random.choice([
            BOOT_RESOURCE_FILE_TYPE.TGZ,
            BOOT_RESOURCE_FILE_TYPE.DDTGZ])

    def test_creates_boot_resource(self):
        name = factory.make_name('name')
        title = factory.make_name('title')
        architecture = make_usable_architecture(self)
        filetype = self.pick_filetype()
        size = random.randint(1024, 2048)
        content = factory.make_string(size).encode('utf-8')
        upload_name = factory.make_name('filename')
        uploaded_file = SimpleUploadedFile(content=content, name=upload_name)
        data = {
            'name': name,
            'title': title,
            'architecture': architecture,
            'filetype': filetype,
            }
        form = BootResourceForm(data=data, files={'content': uploaded_file})
        self.assertTrue(form.is_valid(), form._errors)
        form.save()
        resource = BootResource.objects.get(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED,
            name=name, architecture=architecture)
        resource_set = resource.sets.first()
        rfile = resource_set.files.first()
        self.assertEqual(title, resource.extra['title'])
        self.assertTrue(filetype, rfile.filetype)
        self.assertTrue(filetype, rfile.filename)
        self.assertTrue(size, rfile.largefile.total_size)
        with rfile.largefile.content.open('rb') as stream:
            written_content = stream.read()
        self.assertEqual(content, written_content)

    def test_adds_boot_resource_set_to_existing_boot_resource(self):
        name = factory.make_name('name')
        architecture = make_usable_architecture(self)
        resource = factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED,
            name=name, architecture=architecture)
        filetype = self.pick_filetype()
        size = random.randint(1024, 2048)
        content = factory.make_string(size).encode('utf-8')
        upload_name = factory.make_name('filename')
        uploaded_file = SimpleUploadedFile(content=content, name=upload_name)
        data = {
            'name': name,
            'architecture': architecture,
            'filetype': filetype,
            }
        form = BootResourceForm(data=data, files={'content': uploaded_file})
        self.assertTrue(form.is_valid(), form._errors)
        form.save()
        resource = reload_object(resource)
        resource_set = resource.sets.order_by('id').last()
        rfile = resource_set.files.first()
        self.assertTrue(filetype, rfile.filetype)
        self.assertTrue(filetype, rfile.filename)
        self.assertTrue(size, rfile.largefile.total_size)
        with rfile.largefile.content.open('rb') as stream:
            written_content = stream.read()
        self.assertEqual(content, written_content)

    def test_creates_boot_resource_set_with_version_name_from_now(self):
        now = datetime.now()
        self.patch(forms, 'now').return_value = now
        name = factory.make_name('name')
        title = factory.make_name('title')
        architecture = make_usable_architecture(self)
        filetype = self.pick_filetype()
        size = random.randint(1024, 2048)
        content = factory.make_string(size).encode('utf-8')
        upload_name = factory.make_name('filename')
        uploaded_file = SimpleUploadedFile(content=content, name=upload_name)
        data = {
            'name': name,
            'title': title,
            'architecture': architecture,
            'filetype': filetype,
            }
        form = BootResourceForm(data=data, files={'content': uploaded_file})
        self.assertTrue(form.is_valid(), form._errors)
        form.save()
        resource = BootResource.objects.get(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED,
            name=name, architecture=architecture)
        resource_set = resource.sets.first()
        self.assertEqual(now.strftime('%Y%m%d%H%M%S'), resource_set.version)

    def test_requires_fields(self):
        form = BootResourceForm(data={})
        self.assertFalse(form.is_valid(), form.errors)
        self.assertItemsEqual([
            'name', 'architecture', 'filetype', 'content',
            ],
            form.errors.keys())
