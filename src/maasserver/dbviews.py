# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Postgres Views

Views are implemented in the database to better encapsulate complex queries,
and are recreated during the `dbupgrade` process.
"""

__all__ = [
    "drop_all_views",
    "register_all_views",
    "register_view",
    ]

from contextlib import closing
from textwrap import dedent

from django.db import connection
from maasserver.utils.orm import transactional


def _drop_view_if_exists(view_name):
    """Re-registers the specified view."""
    view_sql = "DROP VIEW IF EXISTS %s;" % view_name
    with closing(connection.cursor()) as cursor:
        cursor.execute(view_sql)


def _register_view(view_name, view_sql):
    """Re-registers the specified view."""
    view_sql = dedent("""\
        CREATE OR REPLACE VIEW %s AS (%s);
        """) % (view_name, view_sql)
    with closing(connection.cursor()) as cursor:
        cursor.execute(view_sql)

# Note that the `Discovery` model object is backed by this view. Any
# changes made to this view should be reflected there.
maasserver_discovery = dedent("""\
    SELECT
        DISTINCT ON (neigh.mac_address, neigh.ip)
        neigh.id AS id, -- Django needs a primary key for the object.
        -- The following will create a string like "<ip>,<mac>", convert
        -- it to base64, and strip out any embedded linefeeds.
        REPLACE(ENCODE(BYTEA(TRIM(TRAILING '/32' FROM neigh.ip::TEXT)
            || ',' || neigh.mac_address::text), 'base64'), CHR(10), '')
            AS discovery_id, -- This can be used as a surrogate key.
        neigh.id AS neighbour_id,
        neigh.ip AS ip,
        neigh.mac_address AS mac_address,
        neigh.vid AS vid,
        GREATEST(neigh.updated, mdns.updated) AS last_seen,
        mdns.id AS mdns_id,
        mdns.hostname AS hostname,
        node.id AS observer_id,
        node.system_id AS observer_system_id,
        node.hostname AS observer_hostname, -- This will be the rack hostname.
        iface.id AS observer_interface_id,
        iface.name AS observer_interface_name,
        fabric.id AS fabric_id,
        fabric.name AS fabric_name,
        -- Note: This VLAN is associated with the physical interface, so the
        -- actual observed VLAN is actually the 'vid' value on the 'fabric'.
        -- (this may or may not have an associated VLAN interface on the rack;
        -- we can sometimes see traffic from unconfigured VLANs.)
        vlan.id AS vlan_id,
        subnet.id AS subnet_id,
        subnet.cidr AS subnet_cidr,
        MASKLEN(subnet.cidr) AS subnet_prefixlen
    FROM maasserver_neighbour neigh
    JOIN maasserver_interface iface ON neigh.interface_id = iface.id
    JOIN maasserver_node node ON node.id = iface.node_id
    JOIN maasserver_vlan vlan ON iface.vlan_id = vlan.id
    JOIN maasserver_fabric fabric ON vlan.fabric_id = fabric.id
    LEFT OUTER JOIN maasserver_mdns mdns ON mdns.ip = neigh.ip
    LEFT OUTER JOIN maasserver_subnet subnet ON (
        vlan.id = subnet.vlan_id
        -- This checks if the IP address is within a known subnet.
        AND neigh.ip << subnet.cidr
    )
    ORDER BY
        neigh.mac_address,
        neigh.ip,
        neigh.updated DESC, -- We want the most recently seen neighbour.
        mdns.updated DESC, -- We want the most recently seen hostname.
        subnet_prefixlen DESC -- We want the best-match CIDR.
    """)

# Views that are helpful for supporting MAAS.
# These can be batch-run using the maas-region-support-dump script.
maas_support__node_overview = dedent("""\
    SELECT
        hostname,
        system_id,
        cpu_count "cpu",
        memory
    FROM maasserver_node
    WHERE
        node_type = 0 -- Machine
    ORDER BY hostname
    """)

maas_support__device_overview = dedent("""\
    SELECT
        node.hostname,
        node.system_id,
        parent.hostname "parent"
    FROM maasserver_node node
    LEFT OUTER JOIN maasserver_node parent
        on node.parent_id = parent.id
    WHERE
        node.node_type = 1
    ORDER BY hostname
    """)

maas_support__node_networking = dedent("""\
    SELECT
        node.hostname,
        iface.id "ifid",
        iface.name,
        iface.type,
        iface.mac_address,
        sip.ip,
        CASE
            WHEN sip.alloc_type = 0 THEN 'AUTO'
            WHEN sip.alloc_type = 1 THEN 'STICKY'
            WHEN sip.alloc_type = 4 THEN 'USER_RESERVED'
            WHEN sip.alloc_type = 5 THEN 'DHCP'
            WHEN sip.alloc_type = 6 THEN 'DISCOVERED'
            ELSE CAST(sip.alloc_type as CHAR)
        END "alloc_type",
        subnet.cidr,
        vlan.vid,
        fabric.name fabric
    FROM maasserver_interface iface
        LEFT OUTER JOIN maasserver_interface_ip_addresses ifip
            on ifip.interface_id = iface.id
        LEFT OUTER JOIN maasserver_staticipaddress sip
            on ifip.staticipaddress_id = sip.id
        LEFT OUTER JOIN maasserver_subnet subnet
            on sip.subnet_id = subnet.id
        LEFT OUTER JOIN maasserver_node node
            on node.id = iface.node_id
        LEFT OUTER JOIN maasserver_vlan vlan
            on vlan.id = subnet.vlan_id
        LEFT OUTER JOIN maasserver_fabric fabric
            on fabric.id = vlan.fabric_id
        ORDER BY
            node.hostname, iface.name, sip.alloc_type
    """)


maas_support__boot_source_selections = dedent("""\
    SELECT
        bs.url,
        bss.release,
        bss.arches,
        bss.subarches,
        bss.labels,
        bss.os
    FROM
        maasserver_bootsource bs
    LEFT OUTER JOIN maasserver_bootsourceselection bss
        ON bss.boot_source_id = bs.id
     """)

maas_support__boot_source_cache = dedent("""\
    SELECT
        bs.url,
        bsc.label,
        bsc.os,
        bsc.release,
        bsc.arch,
        bsc.subarch
    FROM
        maasserver_bootsource bs
    LEFT OUTER JOIN maasserver_bootsourcecache bsc
        ON bsc.boot_source_id = bs.id
    ORDER BY
        bs.url,
        bsc.label,
        bsc.os,
        bsc.release,
        bsc.arch,
        bsc.subarch
     """)

maas_support__configuration__excluding_rpc_shared_secret = dedent("""\
    SELECT
        name,
        value
    FROM
        maasserver_config
    WHERE
        name != 'rpc_shared_secret'
    """)

maas_support__license_keys_present__excluding_key_material = dedent("""\
    SELECT
        osystem,
        distro_series
    FROM
        maasserver_licensekey
    """)

maas_support__ssh_keys__by_user = dedent("""\
    SELECT
        u.username,
        sshkey.key
    FROM
        auth_user u
    LEFT OUTER JOIN maasserver_sshkey sshkey
        ON u.id = sshkey.user_id
    ORDER BY
        u.username,
        sshkey.key
    """)

maas_support__commissioning_result_summary = dedent("""\
    SELECT
        node.hostname,
        count(nr) "result_count",
        max(nr.script_result) "max_script_result",
        max(nr.result_type) "max_result_type"
    FROM
        maasserver_node node
    LEFT OUTER JOIN metadataserver_noderesult nr
        ON nr.node_id = node.id
    WHERE
        node.node_type = 0
    GROUP BY
        node.hostname
    ORDER BY
        node.hostname
    """)


# Dictionary of view_name: view_sql tuples which describe the database views.
_ALL_VIEWS = {
    "maasserver_discovery": maasserver_discovery,
    "maas_support__node_overview": maas_support__node_overview,
    "maas_support__device_overview": maas_support__device_overview,
    "maas_support__node_networking": maas_support__node_networking,
    "maas_support__boot_source_selections":
        maas_support__boot_source_selections,
    "maas_support__boot_source_cache": maas_support__boot_source_cache,
    "maas_support__configuration__excluding_rpc_shared_secret":
        maas_support__configuration__excluding_rpc_shared_secret,
    "maas_support__license_keys_present__excluding_key_material":
        maas_support__license_keys_present__excluding_key_material,
    "maas_support__ssh_keys__by_user": maas_support__ssh_keys__by_user,
    "maas_support__commissioning_result_summary":
        maas_support__commissioning_result_summary,
}


@transactional
def register_all_views():
    """Register all views into the database."""
    for view_name, view_sql in _ALL_VIEWS.items():
        _register_view(view_name, view_sql)


@transactional
def drop_all_views():
    """Drop all views from the database.

    This is intended to be called before the database is upgraded, so that the
    schema can be freely changed without worrying about whether or not the
    views depend on the schema.
    """
    for view_name in _ALL_VIEWS.keys():
        _drop_view_if_exists(view_name)


@transactional
def register_view(view_name):
    """Register a view by name. CAUTION: this is only for use in tests."""
    _register_view(view_name, _ALL_VIEWS[view_name])