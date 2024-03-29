#!/usr/bin/python
# known_nodes.py
#
# Copyright (C) 2008-2018 Veselin Penev, https://bitdust.io
#
# This file (known_nodes.py) is part of BitDust Software.
#
# BitDust is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# BitDust Software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with BitDust Software.  If not, see <http://www.gnu.org/licenses/>.
#
# Please contact us if you have any questions at bitdust.io@gmail.com
#
#
#
#

"""
..

module:: known_nodes
"""

#------------------------------------------------------------------------------


def default_nodes():
    """
    List of DHT nodes currently maintained : (host, UDP port number)
    """
    return [
        # by Veselin Penev:
        ('datahaven.net', 14441, ),
        # ('identity.datahaven.net', 14441),
        ('p2p-id.ru', 14441),
        ('bitdust.io', 14441),
        # ('work.offshore.ai', 14441),
        # ('whmcs.whois.ai', 14441),
        ('blog.bitdust.io', 14441, ),
        ('bitdust.ai', 14441, ),
        ('veselin-p2p.ru', 14441, ),
        ('test.zenaida.ai', 14441, ),
    ]


def nodes():
    """
    Here is a well known DHT nodes, this is "genesys" network.
    Every new node in the network will first connect one or several of those nodes,
    and then will be routed to some other nodes already registered.

    Right now we have started several BitDust nodes on vps hostsing across the world.
    If you willing to support the project and already started your own BitDust node on reliable machine,
    contact us and we will include your address here.
    So other nodes will be able to use your machine to connect to DHT network.

    The load is not big, but as network will grow we will have more machines listed here,
    so all traffic, maintanance and ownership will be distributed across the world.

    You can override those "genesis" nodes by configuring list of your preferred DHT nodes
    (host or IP address) in the program settings:

        api.config_set(
            "services/entangled-dht/known-nodes",
            "firstnode.net:14441, secondmachine.com:1234, 123.45.67.89:9999",
        )

    This way you can create your own DHT network, inside BitDust, under your full control.
    """

    try:
        from main import config
        overridden_dht_nodes_str = str(config.conf().getData('services/entangled-dht/known-nodes'))
    except:
        overridden_dht_nodes_str = ''
    if not overridden_dht_nodes_str:
        return default_nodes()

    overridden_dht_nodes = []
    for dht_node_str in overridden_dht_nodes_str.split(','):
        if dht_node_str.strip():
            try:
                dht_node = dht_node_str.strip().split(':')
                dht_node_host = dht_node[0].strip()
                dht_node_port = int(dht_node[1].strip())
            except:
                continue
            overridden_dht_nodes.append((dht_node_host, dht_node_port, ))

    if overridden_dht_nodes:
        return overridden_dht_nodes

    return default_nodes()
