# Copyright 2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Views for node commissioning/installation results."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    'NodeCommissionResultListView',
    ]

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.views.generic import DetailView
from maasserver.models import Node
from maasserver.views import PaginatedListView
from metadataserver.enum import RESULT_TYPE
from metadataserver.models import NodeResult


class NodeCommissionResultListView(PaginatedListView):

    template_name = 'metadataserver/nodecommissionresult_list.html'
    context_object_name = 'results_list'

    def get_filter_system_ids(self):
        """Return the list of nodes that were selected for filtering."""
        return self.request.GET.getlist('node')

    def get_context_data(self, **kwargs):
        context = super(NodeCommissionResultListView, self).get_context_data(
            **kwargs)
        system_ids = self.get_filter_system_ids()
        if system_ids is not None and len(system_ids) > 0:
            nodes = Node.objects.filter(system_id__in=system_ids)
            context['nodes_filter'] = ', '.join(
                sorted(node.hostname for node in nodes))
        return context

    def get_queryset(self):
        results = NodeResult.objects.filter(
            result_type=RESULT_TYPE.COMMISSIONING)
        system_ids = self.get_filter_system_ids()
        if system_ids is not None and len(system_ids) > 0:
            results = results.filter(node__system_id__in=system_ids)
        return results.order_by('node', '-created', 'name')


class NodeCommissionResultView(DetailView):

    template_name = 'metadataserver/nodecommissionresult.html'

    def get_object(self):
        result_id = self.kwargs.get('id')
        result = get_object_or_404(NodeResult, id=result_id)
        if not self.request.user.is_superuser and \
           self.request.user != result.node.owner:
            raise PermissionDenied
        return result


class NodeInstallResultView(DetailView):

    template_name = 'metadataserver/nodeinstallresult.html'

    def get_object(self):
        result_id = self.kwargs.get('id')
        result = get_object_or_404(NodeResult, id=result_id)
        if not self.request.user.is_superuser and \
           self.request.user != result.node.owner:
            raise PermissionDenied
        return result
