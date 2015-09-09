# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Postgres Triggers

Triggers are implemented in the database to notify the PostgresListener when
an event occurs. Each trigger should use "CREATE OR REPLACE" so its overrides
its previous trigger. All triggers will be added into the database via the
`start_up` method for regiond.

Each trigger will call a procedure to send the notification. Each procedure
should be named with the table name "maasserver_node" and the action for the
trigger "node_create" followed by "notify".

E.g. "maasserver_node_node_create_notify".
"""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    "register_all_triggers"
    ]

from contextlib import closing
from textwrap import dedent

from django.db import connection
from maasserver.utils.orm import transactional

# Note that the corresponding test module (test_triggers) only tests that the
# triggers and procedures are registered.  The behavior of these procedures
# is tested (end-to-end testing) in test_listeners.  We test it there because
# the asynchronous nature of the PG events makes it easier to test in
# test_listeners where all the Twisted infrastructure is already in place.


# Procedure that is called when a tag is added or removed from a node/device.
# Sends a notify message for node_update or device_update depending on if the
# node is installable.
NODE_TAG_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION %s() RETURNS trigger AS $$
    DECLARE
      node RECORD;
    BEGIN
      SELECT system_id, installable INTO node
      FROM maasserver_node
      WHERE id = %s;

      IF node.installable THEN
        PERFORM pg_notify('node_update',CAST(node.system_id AS text));
      ELSE
        PERFORM pg_notify('device_update',CAST(node.system_id AS text));
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


# Procedure that is called when a tag is updated. This will send the correct
# node_update or device_update notify message for all nodes with this tag.
TAG_NODES_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION tag_update_node_device_notify()
    RETURNS trigger AS $$
    DECLARE
      node RECORD;
    BEGIN
      FOR node IN (
        SELECT maasserver_node.system_id, maasserver_node.installable
        FROM maasserver_node_tags, maasserver_node
        WHERE maasserver_node_tags.tag_id = NEW.id
        AND maasserver_node_tags.node_id = maasserver_node.id)
      LOOP
        IF node.installable THEN
          PERFORM pg_notify('node_update',CAST(node.system_id AS text));
        ELSE
          PERFORM pg_notify('device_update',CAST(node.system_id AS text));
        END IF;
      END LOOP;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


# Procedure that is called when a event is created.
# Sends a notify message for node_update or device_update depending on if the
# link node is installable.
EVENT_NODE_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION event_create_node_device_notify()
    RETURNS trigger AS $$
    DECLARE
      node RECORD;
    BEGIN
      SELECT system_id, installable INTO node
      FROM maasserver_node
      WHERE id = NEW.node_id;

      IF node.installable THEN
        PERFORM pg_notify('node_update',CAST(node.system_id AS text));
      ELSE
        PERFORM pg_notify('device_update',CAST(node.system_id AS text));
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


# Procedure that is called when a NodeGroupInterface is added, updated, or
# deleted from a `NodeGroup`. Sends a notify message for nodegroup_update.
NODEGROUP_INTERFACE_NODEGROUP_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION %s() RETURNS trigger AS $$
    DECLARE
      nodegroup RECORD;
    BEGIN
      PERFORM pg_notify('nodegroup_update',CAST(%s AS text));
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


# Procedure that is called when a static ip address is linked or unlinked to
# a MAC address. Sends a notify message for node_update or device_update
# depending on if the node is installable.
MACSTATICIPADDRESSLINK_NODE_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION %s() RETURNS trigger AS $$
    DECLARE
      node RECORD;
    BEGIN
      SELECT system_id, installable INTO node
      FROM maasserver_node, maasserver_macaddress
      WHERE maasserver_node.id = maasserver_macaddress.node_id
      AND maasserver_macaddress.id = %s;

      IF node.installable THEN
        PERFORM pg_notify('node_update',CAST(node.system_id AS text));
      ELSE
        PERFORM pg_notify('device_update',CAST(node.system_id AS text));
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


# Procedure that is called when a dhcplease is added or removed and it matches
# a MAC address. Sends a notify message for node_update or device_update
# depending on if the node is installable.
DHCPLEASE_NODE_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION %s() RETURNS trigger AS $$
    DECLARE
      node RECORD;
    BEGIN
      SELECT system_id, installable INTO node
      FROM maasserver_node, maasserver_macaddress
      WHERE maasserver_node.id = maasserver_macaddress.node_id
      AND maasserver_macaddress.mac_address = %s;

      IF node.installable THEN
        PERFORM pg_notify('node_update',CAST(node.system_id AS text));
      ELSE
        PERFORM pg_notify('device_update',CAST(node.system_id AS text));
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


# Procedure that is called when a MAC address updated. Will send node_update
# or device_update when the MAC address is moved from another node to a new
# node. Sends a notify message for node_update or device_update depending on
# if the node is installable, both for the old node and the new node.
MACADDRESS_UPDATE_NODE_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION nd_macaddress_update_notify()
    RETURNS trigger AS $$
    DECLARE
      node RECORD;
    BEGIN
      IF OLD.node_id != NEW.node_id THEN
        SELECT system_id, installable INTO node
        FROM maasserver_node
        WHERE id = OLD.node_id;

        IF node.installable THEN
          PERFORM pg_notify('node_update',CAST(node.system_id AS text));
        ELSE
          PERFORM pg_notify('device_update',CAST(node.system_id AS text));
        END IF;
      END IF;

      SELECT system_id, installable INTO node
      FROM maasserver_node
      WHERE id = NEW.node_id;

      IF node.installable THEN
        PERFORM pg_notify('node_update',CAST(node.system_id AS text));
      ELSE
        PERFORM pg_notify('device_update',CAST(node.system_id AS text));
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


# Procedure that is called when a physical or virtual block device is updated.
# Sends a notify message for node_update or device_update depending on if the
# node is installable.
PHYSICAL_OR_VIRTUAL_BLOCK_DEVICE_NODE_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION %s() RETURNS trigger AS $$
    DECLARE
      node RECORD;
    BEGIN
      SELECT system_id, installable INTO node
      FROM maasserver_node, maasserver_blockdevice
      WHERE maasserver_node.id = maasserver_blockdevice.node_id
      AND maasserver_blockdevice.id = %s;

      IF node.installable THEN
        PERFORM pg_notify('node_update',CAST(node.system_id AS text));
      ELSE
        PERFORM pg_notify('device_update',CAST(node.system_id AS text));
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


# Procedure that is called when the partition table on a block device is
# updated.
PARTITIONTABLE_NODE_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION %s() RETURNS TRIGGER AS $$
    DECLARE
      node RECORD;
    BEGIN
      SELECT system_id INTO node
      FROM maasserver_node, maasserver_blockdevice
        WHERE maasserver_node.id = maasserver_blockdevice.node_id
        AND maasserver_blockdevice.id = %s;

      PERFORM pg_notify('node_update',CAST(node.system_id AS text));
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


# Procedure that is called when the partition on a partition table is updated.
PARTITION_NODE_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION %s() RETURNS trigger as $$
    DECLARE
      node RECORD;
    BEGIN
      SELECT system_id INTO node
      FROM maasserver_node,
           maasserver_blockdevice,
           maasserver_partitiontable
      WHERE maasserver_node.id = maasserver_blockdevice.node_id
      AND maasserver_blockdevice.id = maasserver_partitiontable.block_device_id
      AND maasserver_partitiontable.id = %s;

      PERFORM pg_notify('node_update',CAST(node.system_id AS text));
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


# Procedure that is called when the filesystem on a partition is updated.
FILESYSTEM_NODE_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION %s() RETURNS trigger as $$
    DECLARE
      node RECORD;
    BEGIN
      SELECT system_id INTO node
      FROM maasserver_node,
           maasserver_blockdevice,
           maasserver_partition,
           maasserver_partitiontable
      WHERE maasserver_node.id = maasserver_blockdevice.node_id
      AND maasserver_blockdevice.id = %s
      OR (maasserver_blockdevice.id =
              maasserver_partitiontable.block_device_id
          AND maasserver_partitiontable.id =
              maasserver_partition.partition_table_id
          AND maasserver_partition.id = %s);

      IF node.system_id != '' THEN
          PERFORM pg_notify('node_update',CAST(node.system_id AS text));
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


# Procedure that is called when the filesystemgroup is updated.
FILESYSTEMGROUP_NODE_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION %s() RETURNS trigger as $$
    DECLARE
      node RECORD;
    BEGIN
      SELECT system_id INTO node
      FROM maasserver_node,
           maasserver_blockdevice,
           maasserver_partition,
           maasserver_partitiontable,
           maasserver_filesystem
      WHERE maasserver_node.id = maasserver_blockdevice.node_id
      AND maasserver_blockdevice.id = maasserver_partitiontable.block_device_id
      AND maasserver_partitiontable.id =
          maasserver_partition.partition_table_id
      AND maasserver_partition.id = maasserver_filesystem.partition_id
      AND (maasserver_filesystem.filesystem_group_id = %s
          OR maasserver_filesystem.cache_set_id = %s);

      IF node.system_id != '' THEN
          PERFORM pg_notify('node_update',CAST(node.system_id AS text));
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


# Procedure that is called when the cacheset is updated.
CACHESET_NODE_NOTIFY = dedent("""\
    CREATE OR REPLACE FUNCTION %s() RETURNS trigger as $$
    DECLARE
      node RECORD;
    BEGIN
      SELECT system_id INTO node
      FROM maasserver_node,
           maasserver_blockdevice,
           maasserver_partition,
           maasserver_partitiontable,
           maasserver_filesystem
      WHERE maasserver_node.id = maasserver_blockdevice.node_id
      AND maasserver_blockdevice.id = maasserver_partitiontable.block_device_id
      AND maasserver_partitiontable.id =
          maasserver_partition.partition_table_id
      AND maasserver_partition.id = maasserver_filesystem.partition_id
      AND maasserver_filesystem.cache_set_id = %s;

      IF node.system_id != '' THEN
          PERFORM pg_notify('node_update',CAST(node.system_id AS text));
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


def render_notification_procedure(proc_name, event_name, cast):
    return dedent("""\
        CREATE OR REPLACE FUNCTION %s() RETURNS trigger AS $$
        DECLARE
        BEGIN
          PERFORM pg_notify('%s',CAST(%s AS text));
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """ % (proc_name, event_name, cast))


def render_node_related_notification_procedure(proc_name, node_id_relation):
    return dedent("""\
        CREATE OR REPLACE FUNCTION %s() RETURNS trigger AS $$
        DECLARE
          node RECORD;
        BEGIN
          SELECT system_id, installable INTO node
          FROM maasserver_node
          WHERE id = %s;

          IF node.installable THEN
            PERFORM pg_notify('node_update',CAST(node.system_id AS text));
          ELSE
            PERFORM pg_notify('device_update',CAST(node.system_id AS text));
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """ % (proc_name, node_id_relation))


def register_trigger(table, procedure, event, params=None, when="after"):
    """Register `trigger` on `table` if it doesn't exist."""
    trigger_name = "%s_%s" % (table, procedure)
    if params is not None:
        filter = 'WHEN (' + ''.join(
            [
                "%s = '%s'" % (key, value)
                for key, value in params.items()
            ]) + ')'
    else:
        filter = ''
    trigger_sql = dedent("""\
        DROP TRIGGER IF EXISTS %s ON %s;
        CREATE TRIGGER %s
        %s %s ON %s
        FOR EACH ROW
        %s
        EXECUTE PROCEDURE %s();
        """) % (
        trigger_name,
        table,
        trigger_name,
        when.upper(),
        event.upper(),
        table,
        filter,
        procedure,
        )
    with closing(connection.cursor()) as cursor:
        cursor.execute(trigger_sql)


def register_procedure(procedure):
    """Register the `procedure` SQL."""
    with closing(connection.cursor()) as cursor:
        cursor.execute(procedure)


@transactional
def register_all_triggers():
    """Register all triggers into the database."""
    # Node(installable) table
    register_procedure(
        render_notification_procedure(
            'node_create_notify', 'node_create', 'NEW.system_id'))
    register_procedure(
        render_notification_procedure(
            'node_update_notify', 'node_update', 'NEW.system_id'))
    register_procedure(
        render_notification_procedure(
            'node_delete_notify', 'node_delete', 'OLD.system_id'))
    register_trigger(
        "maasserver_node", "node_create_notify", "insert",
        {'NEW.installable': True})
    register_trigger(
        "maasserver_node", "node_update_notify", "update",
        {'NEW.installable': True})
    register_trigger(
        "maasserver_node", "node_delete_notify", "delete",
        {'OLD.installable': True})

    # Node(device) table
    register_procedure(
        render_notification_procedure(
            'device_create_notify', 'device_create', 'NEW.system_id'))
    register_procedure(
        render_notification_procedure(
            'device_update_notify', 'device_update', 'NEW.system_id'))
    register_procedure(
        render_notification_procedure(
            'device_delete_notify', 'device_delete', 'OLD.system_id'))
    register_trigger(
        "maasserver_node", "device_create_notify", "insert",
        {'NEW.installable': False})
    register_trigger(
        "maasserver_node", "device_update_notify", "update",
        {'NEW.installable': False})
    register_trigger(
        "maasserver_node", "device_delete_notify", "delete",
        {'OLD.installable': False})

    # Nodegroup table
    register_procedure(
        render_notification_procedure(
            'nodegroup_create_notify', 'nodegroup_create', 'NEW.id'))
    register_procedure(
        render_notification_procedure(
            'nodegroup_update_notify', 'nodegroup_update', 'NEW.id'))
    register_procedure(
        render_notification_procedure(
            'nodegroup_delete_notify', 'nodegroup_delete', 'OLD.id'))
    register_trigger(
        "maasserver_nodegroup", "nodegroup_create_notify", "insert")
    register_trigger(
        "maasserver_nodegroup", "nodegroup_update_notify", "update")
    register_trigger(
        "maasserver_nodegroup", "nodegroup_delete_notify", "delete")

    # Nodegroup interface table
    register_procedure(
        NODEGROUP_INTERFACE_NODEGROUP_NOTIFY % (
            'nodegroupinterface_create_notify',
            'NEW.nodegroup_id',
            ))
    register_procedure(
        NODEGROUP_INTERFACE_NODEGROUP_NOTIFY % (
            'nodegroupinterface_update_notify',
            'NEW.nodegroup_id',
            ))
    register_procedure(
        NODEGROUP_INTERFACE_NODEGROUP_NOTIFY % (
            'nodegroupinterface_delete_notify',
            'OLD.nodegroup_id',
            ))
    register_trigger(
        "maasserver_nodegroupinterface",
        "nodegroupinterface_create_notify", "insert")
    register_trigger(
        "maasserver_nodegroupinterface",
        "nodegroupinterface_update_notify", "update")
    register_trigger(
        "maasserver_nodegroupinterface",
        "nodegroupinterface_delete_notify", "delete")

    # Zone table
    register_procedure(
        render_notification_procedure(
            'zone_create_notify', 'zone_create', 'NEW.id'))
    register_procedure(
        render_notification_procedure(
            'zone_update_notify', 'zone_update', 'NEW.id'))
    register_procedure(
        render_notification_procedure(
            'zone_delete_notify', 'zone_delete', 'OLD.id'))
    register_trigger(
        "maasserver_zone", "zone_create_notify", "insert")
    register_trigger(
        "maasserver_zone", "zone_update_notify", "update")
    register_trigger(
        "maasserver_zone", "zone_delete_notify", "delete")

    # Tag table
    register_procedure(
        render_notification_procedure(
            'tag_create_notify', 'tag_create', 'NEW.id'))
    register_procedure(
        render_notification_procedure(
            'tag_update_notify', 'tag_update', 'NEW.id'))
    register_procedure(
        render_notification_procedure(
            'tag_delete_notify', 'tag_delete', 'OLD.id'))
    register_trigger(
        "maasserver_tag", "tag_create_notify", "insert")
    register_trigger(
        "maasserver_tag", "tag_update_notify", "update")
    register_trigger(
        "maasserver_tag", "tag_delete_notify", "delete")

    # Node tag link table
    register_procedure(
        NODE_TAG_NOTIFY % (
            'node_device_tag_link_notify',
            'NEW.node_id',
            ))
    register_procedure(
        NODE_TAG_NOTIFY % (
            'node_device_tag_unlink_notify',
            'OLD.node_id',
            ))
    register_trigger(
        "maasserver_node_tags", "node_device_tag_link_notify", "insert")
    register_trigger(
        "maasserver_node_tags", "node_device_tag_unlink_notify", "delete")

    # Tag table, update to linked nodes.
    register_procedure(TAG_NODES_NOTIFY)
    register_trigger(
        "maasserver_tag", "tag_update_node_device_notify", "update")

    # User table
    register_procedure(
        render_notification_procedure(
            'user_create_notify', 'user_create', 'NEW.id'))
    register_procedure(
        render_notification_procedure(
            'user_update_notify', 'user_update', 'NEW.id'))
    register_procedure(
        render_notification_procedure(
            'user_delete_notify', 'user_delete', 'OLD.id'))
    register_trigger(
        "auth_user", "user_create_notify", "insert")
    register_trigger(
        "auth_user", "user_update_notify", "update")
    register_trigger(
        "auth_user", "user_delete_notify", "delete")

    # Events table
    register_procedure(
        render_notification_procedure(
            'event_create_notify', 'event_create', 'NEW.id'))
    register_procedure(
        render_notification_procedure(
            'event_update_notify', 'event_update', 'NEW.id'))
    register_procedure(
        render_notification_procedure(
            'event_delete_notify', 'event_delete', 'OLD.id'))
    register_trigger(
        "maasserver_event", "event_create_notify", "insert")
    register_trigger(
        "maasserver_event", "event_update_notify", "update")
    register_trigger(
        "maasserver_event", "event_delete_notify", "delete")

    # Events table, update to linked node.
    register_procedure(EVENT_NODE_NOTIFY)
    register_trigger(
        "maasserver_event", "event_create_node_device_notify", "insert")

    # MAC static ip address table, update to linked node.
    register_procedure(
        MACSTATICIPADDRESSLINK_NODE_NOTIFY % (
            'nd_sipaddress_link_notify',
            'NEW.mac_address_id',
            ))
    register_procedure(
        MACSTATICIPADDRESSLINK_NODE_NOTIFY % (
            'nd_sipaddress_unlink_notify',
            'OLD.mac_address_id',
            ))
    register_trigger(
        "maasserver_macstaticipaddresslink",
        "nd_sipaddress_link_notify", "insert")
    register_trigger(
        "maasserver_macstaticipaddresslink",
        "nd_sipaddress_unlink_notify", "delete")

    # DHCP lease table, update to linked node.
    register_procedure(
        DHCPLEASE_NODE_NOTIFY % (
            'nd_dhcplease_match_notify',
            'NEW.mac',
            ))
    register_procedure(
        DHCPLEASE_NODE_NOTIFY % (
            'nd_dhcplease_unmatch_notify',
            'OLD.mac',
            ))
    register_trigger(
        "maasserver_dhcplease",
        "nd_dhcplease_match_notify", "insert")
    register_trigger(
        "maasserver_dhcplease",
        "nd_dhcplease_unmatch_notify", "delete")

    # Node result table, update to linked node.
    register_procedure(
        render_node_related_notification_procedure(
            'nd_noderesult_link_notify', 'NEW.node_id'))
    register_procedure(
        render_node_related_notification_procedure(
            'nd_noderesult_unlink_notify', 'OLD.node_id'))
    register_trigger(
        "metadataserver_noderesult",
        "nd_noderesult_link_notify", "insert")
    register_trigger(
        "metadataserver_noderesult",
        "nd_noderesult_unlink_notify", "delete")

    # MAC address table, update to linked node.
    register_procedure(
        render_node_related_notification_procedure(
            'nd_macaddress_link_notify', 'NEW.node_id'))
    register_procedure(
        render_node_related_notification_procedure(
            'nd_macaddress_unlink_notify', 'OLD.node_id'))
    register_procedure(MACADDRESS_UPDATE_NODE_NOTIFY)
    register_trigger(
        "maasserver_macaddress",
        "nd_macaddress_link_notify", "insert")
    register_trigger(
        "maasserver_macaddress",
        "nd_macaddress_unlink_notify", "delete")
    register_trigger(
        "maasserver_macaddress",
        "nd_macaddress_update_notify", "update")

    # Block device table, update to linked node.
    register_procedure(
        render_node_related_notification_procedure(
            'nd_blockdevice_link_notify', 'NEW.node_id'))
    register_procedure(
        render_node_related_notification_procedure(
            'nd_blockdevice_update_notify', 'NEW.node_id'))
    register_procedure(
        render_node_related_notification_procedure(
            'nd_blockdevice_unlink_notify', 'OLD.node_id'))
    register_procedure(
        PHYSICAL_OR_VIRTUAL_BLOCK_DEVICE_NODE_NOTIFY % (
            'nd_physblockdevice_update_notify', 'NEW.blockdevice_ptr_id'))
    register_procedure(
        PHYSICAL_OR_VIRTUAL_BLOCK_DEVICE_NODE_NOTIFY % (
            'nd_virtblockdevice_update_notify', 'NEW.blockdevice_ptr_id'))
    register_trigger(
        "maasserver_blockdevice",
        "nd_blockdevice_link_notify", "insert")
    register_trigger(
        "maasserver_blockdevice",
        "nd_blockdevice_update_notify", "update")
    register_trigger(
        "maasserver_blockdevice",
        "nd_blockdevice_unlink_notify", "delete")
    register_trigger(
        "maasserver_physicalblockdevice",
        "nd_physblockdevice_update_notify", "update")
    register_trigger(
        "maasserver_virtualblockdevice",
        "nd_virtblockdevice_update_notify", "update")

    # Partition table, update to linked user.
    register_procedure(
        PARTITIONTABLE_NODE_NOTIFY % (
            'nd_partitiontable_link_notify', 'NEW.block_device_id'))
    register_procedure(
        PARTITIONTABLE_NODE_NOTIFY % (
            'nd_partitiontable_update_notify', 'NEW.block_device_id'))
    register_procedure(
        PARTITIONTABLE_NODE_NOTIFY % (
            'nd_partitiontable_unlink_notify', 'OLD.block_device_id'))
    register_trigger(
        "maasserver_partitiontable",
        "nd_partitiontable_link_notify", "insert")
    register_trigger(
        "maasserver_partitiontable",
        "nd_partitiontable_update_notify", "update")
    register_trigger(
        "maasserver_partitiontable",
        "nd_partitiontable_unlink_notify", "delete")

    # Partition, update to linked user.
    register_procedure(
        PARTITION_NODE_NOTIFY % (
            'nd_partition_link_notify', 'NEW.partition_table_id'))
    register_procedure(
        PARTITION_NODE_NOTIFY % (
            'nd_partition_update_notify', 'NEW.partition_table_id'))
    register_procedure(
        PARTITION_NODE_NOTIFY % (
            'nd_partition_unlink_notify', 'OLD.partition_table_id'))
    register_trigger(
        "maasserver_partition",
        "nd_partition_link_notify", "insert")
    register_trigger(
        "maasserver_partition",
        "nd_partition_update_notify", "update")
    register_trigger(
        "maasserver_partition",
        "nd_partition_unlink_notify", "delete")

    # Filesystem, update to linked user.
    register_procedure(
        FILESYSTEM_NODE_NOTIFY % (
            'nd_filesystem_link_notify', 'NEW.block_device_id',
            'NEW.partition_id'))
    register_procedure(
        FILESYSTEM_NODE_NOTIFY % (
            'nd_filesystem_update_notify', 'NEW.block_device_id',
            'NEW.partition_id'))
    register_procedure(
        FILESYSTEM_NODE_NOTIFY % (
            'nd_filesystem_unlink_notify', 'OLD.block_device_id',
            'OLD.partition_id'))
    register_trigger(
        "maasserver_filesystem",
        "nd_filesystem_link_notify", "insert")
    register_trigger(
        "maasserver_filesystem",
        "nd_filesystem_update_notify", "update")
    register_trigger(
        "maasserver_filesystem",
        "nd_filesystem_unlink_notify", "delete")

    # Filesystemgroup, update to linked user.
    register_procedure(
        FILESYSTEMGROUP_NODE_NOTIFY % (
            'nd_filesystemgroup_link_notify', 'NEW.id', 'NEW.cache_set_id'))
    register_procedure(
        FILESYSTEMGROUP_NODE_NOTIFY % (
            'nd_filesystemgroup_update_notify', 'NEW.id', 'NEW.cache_set_id'))
    register_procedure(
        FILESYSTEMGROUP_NODE_NOTIFY % (
            'nd_filesystemgroup_unlink_notify', 'OLD.id', 'OLD.cache_set_id'))
    register_trigger(
        "maasserver_filesystemgroup",
        "nd_filesystemgroup_link_notify", "insert")
    register_trigger(
        "maasserver_filesystemgroup",
        "nd_filesystemgroup_update_notify", "update")
    register_trigger(
        "maasserver_filesystemgroup",
        "nd_filesystemgroup_unlink_notify", "delete")

    # Cacheset, update to linked user.
    register_procedure(
        CACHESET_NODE_NOTIFY % (
            'nd_cacheset_link_notify', 'NEW.id'))
    register_procedure(
        CACHESET_NODE_NOTIFY % (
            'nd_cacheset_update_notify', 'NEW.id'))
    register_procedure(
        CACHESET_NODE_NOTIFY % (
            'nd_cacheset_unlink_notify', 'OLD.id'))
    register_trigger(
        "maasserver_cacheset",
        "nd_cacheset_link_notify", "insert")
    register_trigger(
        "maasserver_cacheset",
        "nd_cacheset_update_notify", "update")
    register_trigger(
        "maasserver_cacheset",
        "nd_cacheset_unlink_notify", "delete")

    # SSH key table, update to linked user.
    register_procedure(
        render_notification_procedure(
            'user_sshkey_link_notify', 'user_update', 'NEW.user_id'))
    register_procedure(
        render_notification_procedure(
            'user_sshkey_unlink_notify', 'user_update', 'OLD.user_id'))
    register_trigger(
        "maasserver_sshkey", "user_sshkey_link_notify", "insert")
    register_trigger(
        "maasserver_sshkey", "user_sshkey_unlink_notify", "delete")

    # SSL key table, update to linked user.
    register_procedure(
        render_notification_procedure(
            'user_sslkey_link_notify', 'user_update', 'NEW.user_id'))
    register_procedure(
        render_notification_procedure(
            'user_sslkey_unlink_notify', 'user_update', 'OLD.user_id'))
    register_trigger(
        "maasserver_sslkey", "user_sslkey_link_notify", "insert")
    register_trigger(
        "maasserver_sslkey", "user_sslkey_unlink_notify", "delete")
