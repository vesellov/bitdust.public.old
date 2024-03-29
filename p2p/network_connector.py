#!/usr/bin/env python
# network_connector.py
#
# Copyright (C) 2008-2018 Veselin Penev, https://bitdust.io
#
# This file (network_connector.py) is part of BitDust Software.
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
#

"""
.. module:: network_connector.

.. role:: red

.. raw:: html

    <a href="https://bitdust.io/automats/network_connector/network_connector.png" target="_blank">
    <img src="https://bitdust.io/automats/network_connector/network_connector.png" style="max-width:100%;">
    </a>

The ``network_connector()`` machine is needed to monitor status of the Internet connection.

It will periodically check for incoming traffic and start STUN discovery procedure
to detect connection status and possible external IP changes.

If BitDust get disconnected it will ping "Google dot com" (joke) to check what is going on.


EVENTS:
    * :red:`all-network-transports-disabled`
    * :red:`all-network-transports-ready`
    * :red:`check-reconnect`
    * :red:`connection-done`
    * :red:`gateway-is-not-started`
    * :red:`got-network-info`
    * :red:`init`
    * :red:`internet-failed`
    * :red:`internet-success`
    * :red:`network-down`
    * :red:`network-transport-state-changed`
    * :red:`network-transports-verified`
    * :red:`network-up`
    * :red:`reconnect`
    * :red:`timer-1hour`
    * :red:`timer-5sec`
    * :red:`upnp-done`
"""

#------------------------------------------------------------------------------

_Debug = True
_DebugLevel = 6

#------------------------------------------------------------------------------

import sys
import time

try:
    from twisted.internet import reactor
except:
    sys.exit('Error initializing twisted.internet.reactor in network_connector.py')

from twisted.internet import threads
from twisted.internet.defer import DeferredList

#------------------------------------------------------------------------------

from logs import lg

from automats import automat
from automats import global_state

from system import bpio

from lib import net_misc
from lib import misc

from services import driver

from main import settings
from main import shutdowner

from p2p import p2p_stats

#------------------------------------------------------------------------------

_NetworkConnector = None
_CounterSuccessConnections = 0
_CounterFailedConnections = 0
_LastSuccessConnectionTime = 0

#------------------------------------------------------------------------------


def A(event=None, arg=None):
    """
    Access method to interact with the state machine.
    """
    global _NetworkConnector
    if event is None and arg is None:
        return _NetworkConnector
    if _NetworkConnector is None:
        _NetworkConnector = NetworkConnector(
            'network_connector', 'AT_STARTUP', _DebugLevel, publish_events=True)
    if event is not None:
        _NetworkConnector.automat(event, arg)
    return _NetworkConnector


def Destroy():
    """
    Destroy network_connector() automat and remove its instance from memory.
    """
    global _NetworkConnector
    if _NetworkConnector is None:
        return
    _NetworkConnector.destroy()
    del _NetworkConnector
    _NetworkConnector = None


class NetworkConnector(automat.Automat):
    """
    Class to monitor Internet connection and reconnect when needed.
    """

    timers = {
        'timer-1hour': (3600, ['DISCONNECTED']),
        'timer-5sec': (5.0, ['DISCONNECTED', 'CONNECTED']),
    }

    def init(self):
        self.log_transitions = _Debug
        self.last_upnp_time = 0
        self.last_reconnect_time = 0
        self.last_internet_state = 'disconnected'
        self.last_bytes_in_counter = 0
        net_misc.SetConnectionDoneCallbackFunc(ConnectionDoneCallback)
        net_misc.SetConnectionFailedCallbackFunc(ConnectionFailedCallback)

    def state_changed(self, oldstate, newstate, event, arg):
        global_state.set_global_state('NETWORK ' + newstate)
        if driver.is_on('service_p2p_hookups'):
            from p2p import p2p_connector
            from system import tray_icon
            p2p_connector.A('network_connector.state', newstate)
            tray_icon.state_changed(self.state, p2p_connector.A().state)
        if oldstate != 'CONNECTED' and newstate == 'CONNECTED':
            # TODO: redesign the state machine to cover that
            if self.last_bytes_in_counter < p2p_stats.get_total_bytes_in():
                lg.info('HELLO BITDUST WORLD !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
            else:
                lg.warn('SEEMS I AM OFFLINE !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
            self.last_bytes_in_counter = p2p_stats.get_total_bytes_in()

    def A(self, event, arg):
        #---AT_STARTUP---
        if self.state == 'AT_STARTUP':
            if event == 'init':
                self.state = 'START_UP'
                self.Disconnects=0
                self.Reset=False
                self.ColdStart=True
                self.doCheckNetworkInterfaces(arg)
        #---CONNECTED---
        elif self.state == 'CONNECTED':
            if event == 'reconnect' or ( event == 'timer-5sec' and ( self.Reset or not self.isConnectionAlive(arg) ) ):
                self.state = 'DOWN'
                self.Disconnects=0
                self.Reset=False
                self.doSetDown(arg)
            elif event == 'check-reconnect':
                self.state = 'TRANSPORTS?'
                self.doVerifyTransports(arg)
        #---NETWORK?---
        elif self.state == 'NETWORK?':
            if event == 'got-network-info' and not self.isNetworkActive(arg):
                self.state = 'DISCONNECTED'
            elif event == 'got-network-info' and self.isNetworkActive(arg) and self.isCurrentInterfaceActive(arg):
                self.state = 'INTERNET?'
                self.doPingGoogleDotCom(arg)
            elif event == 'got-network-info' and self.isNetworkActive(arg) and not self.isCurrentInterfaceActive(arg):
                self.state = 'UP'
                self.doSetUp(arg)
        #---INTERNET?---
        elif self.state == 'INTERNET?':
            if event == 'internet-failed':
                self.state = 'DISCONNECTED'
            elif event == 'internet-success':
                self.state = 'UP'
                self.doSetUp(arg)
        #---DISCONNECTED---
        elif self.state == 'DISCONNECTED':
            if event == 'reconnect' or event == 'check-reconnect' or event == 'timer-1hour' or ( event == 'timer-5sec' and ( self.Disconnects < 3 or self.Reset ) ) or ( event == 'connection-done' and self.isTimePassed(arg) ):
                self.state = 'DOWN'
                self.doRememberTime(arg)
                self.Disconnects+=1
                self.Reset=False
                self.doSetDown(arg)
        #---UP---
        elif self.state == 'UP':
            if not self.ColdStart and event == 'network-up' and not self.isNeedUPNP(arg):
                self.state = 'TRANSPORTS?'
                self.doStartNetworkTransports(arg)
            elif event == 'reconnect' or event == 'check-reconnect':
                self.Reset=True
            elif self.ColdStart and event == 'network-up':
                self.state = 'TRANSPORTS?'
                self.doColdStartNetworkTransports(arg)
                self.ColdStart=False
            elif not self.ColdStart and event == 'network-up' and self.isNeedUPNP(arg):
                self.state = 'UPNP'
                self.doUPNP(arg)
        #---DOWN---
        elif self.state == 'DOWN':
            if event == 'network-down':
                self.state = 'NETWORK?'
                self.doCheckNetworkInterfaces(arg)
        #---TRANSPORTS?---
        elif self.state == 'TRANSPORTS?':
            if event == 'reconnect' or event == 'check-reconnect':
                self.Reset=True
            elif not self.Reset and ( ( event == 'all-network-transports-ready' or event == 'network-transports-verified' or event == 'network-transport-state-changed' ) and ( self.isAllReady(arg) and self.isAllListening(arg) ) ):
                self.state = 'CONNECTED'
            elif self.Reset and ( ( event == 'all-network-transports-ready' or event == 'network-transports-verified' or event == 'network-transport-state-changed' ) and self.isAllReady(arg) ):
                self.state = 'DOWN'
                self.Reset=False
                self.Disconnects=0
                self.doSetDown(arg)
            elif ( event == 'all-network-transports-disabled' or event == 'gateway-is-not-started' or event == 'network-transport-state-changed' ) and ( self.isAllReady(arg) and not self.isAllListening(arg) ):
                self.state = 'DISCONNECTED'
        #---START_UP---
        elif self.state == 'START_UP':
            if event == 'got-network-info' and not self.isNetworkActive(arg):
                self.state = 'DISCONNECTED'
                self.Disconnects=3
            elif event == 'reconnect' or event == 'check-reconnect':
                self.state = 'UP'
                self.doSetUp(arg)
        #---UPNP---
        elif self.state == 'UPNP':
            if event == 'upnp-done':
                self.state = 'TRANSPORTS?'
                self.doStartNetworkTransports(arg)
            elif event == 'reconnect' or event == 'check-reconnect':
                self.Reset=True
        return None

    def isNeedUPNP(self, arg):
        if not settings.enableUPNP():
            return False
        if driver.is_on('service_tcp_transport'):
            try:
                from transport.tcp import tcp_node
                if int(tcp_node.get_internal_port()) != int(settings.getTCPPort()):
                    return True
            except:
                lg.exc()
                return False
        return time.time() - self.last_upnp_time > 60 * 60

    def isConnectionAlive(self, arg):
        # miss = 0
        if driver.is_on('service_udp_datagrams'):
            from lib import udp
            if time.time() - udp.get_last_datagram_time() < 60:
                if settings.enableUDP() and settings.enableUDPreceiving():
                    return True
        # else:
        #     miss += 1
        if driver.is_on('service_gateway'):
            from transport import gateway
            if time.time() - gateway.last_inbox_time() < 60:
                return True
            transport_states = map(lambda t: t.state, gateway.transports().values())
            if 'LISTENING' in transport_states:
                return True
            if 'STARTING' in transport_states:
                return True
        # else:
        #     miss += 1
        # if miss >= 2:
        #     return True
        return True  # testing
        return False

    def isNetworkActive(self, arg):
        return len(arg) > 0

    def isCurrentInterfaceActive(self, arg):
        # I am not sure about external IP,
        # because if you have a white IP it should be the same with your local IP
        return (misc.readLocalIP() in arg) or (misc.readExternalIP() in arg)

    def isTimePassed(self, arg):
        return time.time() - self.last_reconnect_time < 15

    def isAllListening(self, arg):
        """
        Condition method.
        """
        if not driver.is_on('service_gateway'):
            if _Debug:
                lg.out(_DebugLevel, 'network_connector.isAllListening returning False : service_gateway is OFF')
            return False
        from transport import gateway
        transports = gateway.transports().values()
        for t in transports:
            if t.state != 'LISTENING':
                if _Debug:
                    lg.out(_DebugLevel, 'network_connector.isAllListening returning False : transport %s is not LISTENING' % t)
                return False
        if _Debug:
            lg.out(_DebugLevel, 'network_connector.isAllListening returning True :  HELLO BITDUST WORLD !!!!!!!!!!!!!!!!!!!!!!')
        return True

    def isAllReady(self, arg):
        """
        Condition method.
        """
        if not driver.is_on('service_gateway'):
            if _Debug:
                lg.out(_DebugLevel, 'network_connector.isAllReady returning False : service_gateway is OFF')
            return False
        LISTENING_count = 0
        OFFLINE_count = 0
        from transport import gateway
        transports = gateway.transports().values()
        for t in transports:
            if t.state != 'OFFLINE' and t.state != 'LISTENING':
                if _Debug:
                    lg.out(_DebugLevel, 'network_connector.isAllReady returning False : transport %s is not READY yet' % t)
                return False
            if t.state == 'OFFLINE':
                OFFLINE_count += 1
            if t.state == 'LISTENING':
                LISTENING_count += 1
        if _Debug:
            lg.out(_DebugLevel, 'network_connector.isAllReady returning True : all transports READY')
            lg.out(_DebugLevel, '    OFFLINE transports:%d, LISTENING transports: %d' % (OFFLINE_count, LISTENING_count))
        return True

    def doSetUp(self, arg):
        if _Debug:
            lg.out(_DebugLevel, 'network_connector.doSetUp')

#         Second attempt
#         l = []
#         for service_name in driver.affecting('service_network'):
#             d = driver.start_single(service_name)
#             l.append(d)
# 
#         def _ok(x):
#             lg.info('network child services is UP')
#             self.automat('network-up')
#             return None
#         
#         def _fail(err):
#             lg.err(err)
#             self.automat('network-up')
#             return None
# 
#         dl = DeferredList(l, fireOnOneErrback=True, consumeErrors=True)
#         dl.addCallback(_ok)
#         d.addErrback(_fail)
        
        # First Solution
        if driver.is_on('service_service_entangled_dht'):
            from dht import dht_service
            dht_service.reconnect()
        if driver.is_on('service_ip_port_responder'):
            from stun import stun_server
            udp_port = int(settings.getUDPPort())
            stun_server.A('start', udp_port)
        if driver.is_on('service_my_ip_port'):
            from stun import stun_client
            stun_client.A().dropMyExternalAddress()
            stun_client.A('start')
        if driver.is_on('service_private_messages'):
            from chat import nickname_holder
            nickname_holder.A('set')
        if driver.is_on('service_udp_datagrams'):
            from lib import udp
            udp_port = settings.getUDPPort()
            if not udp.proto(udp_port):
                try:
                    udp.listen(udp_port)
                except:
                    lg.exc()
        self.automat('network-up')

    def doSetDown(self, arg):
        """
        """
        if _Debug:
            lg.out(_DebugLevel, 'network_connector.doSetDown')

#         Second Approach
#         l = []
#         for service_name in driver.affecting('service_network'):
#             d = driver.stop_single(service_name)
#             l.append(d)
# 
#         def _ok(x):
#             lg.info('network child services is DOWN')
#             self.automat('network-down')
#             return None
#         
#         def _fail(err):
#             lg.err(err)
#             self.automat('network-down')
#             return None
# 
#         dl = DeferredList(l, fireOnOneErrback=True, consumeErrors=True)
#         dl.addCallback(_ok)
#         d.addErrback(_fail)

        # First Solution        
        if driver.is_on('service_gateway'):
            from transport import gateway
            gateway.stop()
        if driver.is_on('service_ip_port_responder'):
            from stun import stun_server
            stun_server.A('stop')
        if driver.is_on('service_service_entangled_dht'):
            from dht import dht_service
            dht_service.disconnect()
        if driver.is_on('service_udp_datagrams'):
            from lib import udp
            udp_port = settings.getUDPPort()
            if udp.proto(udp_port):
                udp.close(udp_port)
        self.automat('network-down')

    def doUPNP(self, arg):
        self.last_upnp_time = time.time()
        UpdateUPNP()

    def doPingGoogleDotCom(self, arg):
        """
        Action method.
        """
        if _Debug:
            lg.out(_DebugLevel, 'network_connector.doPingGoogleDotCom')
        net_misc.TestInternetConnection().addCallbacks(
            lambda x: self.automat('internet-success', 'connected'),
            lambda x: self.automat('internet-failed', 'disconnected'))

    def doCheckNetworkInterfaces(self, arg):
        # lg.out(4, 'network_connector.doCheckNetworkInterfaces')
        # TODO
        # self.automat('got-network-info', [])
        start_time = time.time()
        if bpio.Linux():
            def _call():
                return net_misc.getNetworkInterfaces()

            def _done(result, start_time):
                if _Debug:
                    lg.out(_DebugLevel, 'network_connector.doCheckNetworkInterfaces DONE: %s in %d seconds' % (str(result), time.time() - start_time))
                self.automat('got-network-info', result)
            d = threads.deferToThread(_call)
            d.addBoth(_done, start_time)
        else:
            ips = net_misc.getNetworkInterfaces()
            if _Debug:
                lg.out(_DebugLevel, 'network_connector.doCheckNetworkInterfaces DONE: %s in %d seconds' % (str(ips), time.time() - start_time))
            self.automat('got-network-info', ips)

    def doRememberTime(self, arg):
        self.last_reconnect_time = time.time()

    def doStartNetworkTransports(self, arg):
        """
        Action method.
        """
        if not driver.is_on('service_gateway'):
            self.automat('gateway-is-not-started')
            return
        from transport import gateway
        restarted_transports = gateway.start()
        if len(restarted_transports) == 0:
            self.automat('all-network-transports-ready')

    def doColdStartNetworkTransports(self, arg):
        """
        Action method.
        """
        if not driver.is_on('service_gateway'):
            self.automat('gateway-is-not-started')
            return
        from transport import gateway
        restarted_transports = gateway.cold_start()
        if len(restarted_transports) == 0:
            self.automat('all-network-transports-ready')

    def doVerifyTransports(self, arg):
        """
        Action method.
        """
        if not driver.is_on('service_gateway'):
            self.automat('gateway-is-not-started')
            return
        from transport import gateway

        def _transports_verified(all_results):
            if _Debug:
                lg.out(_DebugLevel, 'network_connector._transports_verified : %s' % str(all_results))
            order, all_results = all_results
            not_valid_count = 0
            restarts_count = 0
            if len(order) == 0:
                self.automat('network-transports-verified')
                return
            for proto in order:
                if not all_results[proto]:
                    not_valid_count += 1
            for priority in range(len(order)):
                proto = order[priority]
                if not all_results[proto]:
                    if _Debug:
                        lg.out(_DebugLevel, '    [%s] at position %d needs restart' % (proto, priority))
                    gateway.transport(proto).automat('restart')
                    restarts_count += 1
                    if not_valid_count > 1:  # this one failed, 2 other failed as well
                        self.automat('network-transports-verified')
                        return
                    continue
                if not_valid_count > 0:
                    if _Debug:
                        lg.out(_DebugLevel, '    skip %d transport [%s]' % (priority, proto))
                    if restarts_count == 0:
                        if _Debug:
                            lg.out(_DebugLevel, '    but no restarts and %d:[%s] is valid' % (priority, proto))
                        self.automat('network-transports-verified')
                    return
                if _Debug:
                    lg.out(_DebugLevel, '        [%s] at position %d is fine, skip other transports' % (proto, priority))
                self.automat('network-transports-verified')
                return
        gateway.verify().addCallback(_transports_verified)

#------------------------------------------------------------------------------


def UpdateUPNP():
    """
    Use ``lib.run_upnpc`` to configure UPnP device to create a port forwarding.
    """
    if _Debug:
        lg.out(_DebugLevel, 'network_connector.UpdateUPNP ')
    protos_need_upnp = set(['tcp', ])
    if not settings.enableTCP():
        # need to update only enabled protocols
        protos_need_upnp.discard('tcp')

    def _update_next_proto():
        if len(protos_need_upnp) == 0:
            lg.out(_DebugLevel, 'network_connector.update_upnp done, sending "upnp-done" event')
            A('upnp-done')
            return
        if _Debug:
            lg.out(_DebugLevel, 'network_connector.UpdateUPNP._update_next_proto ' + str(protos_need_upnp))
        proto = protos_need_upnp.pop()
        protos_need_upnp.add(proto)
        port = -1
        if proto == 'tcp':
            port = settings.getTCPPort()
        if port > 0:
            d = threads.deferToThread(_call_upnp, port)
            d.addCallback(_upnp_proto_done, proto)
        else:
            reactor.callLater(0, _upnp_proto_done, proto)

    def _call_upnp(port):
        # start messing with upnp settings
        # success can be false if you're behind a router that doesn't support upnp
        # or if you are not behind a router at all and have an external ip address
        from system import run_upnpc
        shutdowner.A('block')
        success, port = run_upnpc.update(port)
        shutdowner.A('unblock')
        return (success, port)

    def _upnp_proto_done(result, proto):
        if _Debug:
            lg.out(_DebugLevel, 'network_connector.UpdateUPNP._upnp_proto_done %s: %s' % (proto, str(result)))
        if result[0] == 'upnp-done':
            if proto == 'tcp':
                if str(settings.getTCPPort()) != str(result[1]).strip():
                    lg.out(_DebugLevel, '    !!!!!!!!!! created a new port mapping, TCP port were changed: %s -> %s' % (
                        settings.getTCPPort(), str(result[1])))
                settings.setTCPPort(result[1])
        protos_need_upnp.discard(proto)
        reactor.callLater(0, _update_next_proto)

    _update_next_proto()

#------------------------------------------------------------------------------


def ConnectionDoneCallback(param, proto, info):
    global _CounterSuccessConnections
    global _LastSuccessConnectionTime
    _CounterSuccessConnections += 1
    _LastSuccessConnectionTime = time.time()
    A('connection-done')


def ConnectionFailedCallback(param, proto, info):
    global _CounterFailedConnections
    if proto is not 'udp' and proto is not 'proxy':
        _CounterFailedConnections += 1
    A('connection-failed')
