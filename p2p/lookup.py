#!/usr/bin/python
# lookup.py
#
# Copyright (C) 2008-2018 Veselin Penev, https://bitdust.io
#
# This file (lookup.py) is part of BitDust Software.
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
.. module:: lookup.

.. role:: red
"""

#------------------------------------------------------------------------------

_Debug = True
_DebugLevel = 12

#------------------------------------------------------------------------------

import sys
import time

try:
    from twisted.internet import reactor
except:
    sys.exit('Error initializing twisted.internet.reactor in lookup.py')

from twisted.internet.defer import DeferredList, Deferred

#------------------------------------------------------------------------------

from logs import lg

#------------------------------------------------------------------------------

_KnownIDURLsDict = {}
_DiscoveredIDURLsList = []
_LookupTasks = []
_CurrentLookupTask = None
# _NextLookupTask = None
_LookupMethod = None  # method to get a list of random nodes
_ObserveMethod = None  # method to get IDURL from given node
_ProcessMethod = None  # method to do some stuff with discovered IDURL

#------------------------------------------------------------------------------


def init(lookup_method=None, observe_method=None, process_method=None):
    """
    """
    global _LookupMethod
    global _ObserveMethod
    global _ProcessMethod
    _LookupMethod = lookup_method
    _ObserveMethod = observe_method
    _ProcessMethod = process_method
    if _Debug:
        lg.out(_DebugLevel, "lookup.init")


def shutdown():
    """
    """
    global _LookupMethod
    global _ObserveMethod
    global _ProcessMethod
    _LookupMethod = None
    _ObserveMethod = None
    _ProcessMethod = None
    if _Debug:
        lg.out(_DebugLevel, "lookup.shutdown")

#------------------------------------------------------------------------------


def known_idurls():
    global _KnownIDURLsDict
    return _KnownIDURLsDict


def discovered_idurls():
    global _DiscoveredIDURLsList
    return _DiscoveredIDURLsList

#------------------------------------------------------------------------------


def consume_discovered_idurls(count=1):
    if not discovered_idurls():
        if _Debug:
            lg.out(_DebugLevel, 'lookup.consume_discovered_idurls returns empty list')
        return []
    results = []
    while len(results) < count and discovered_idurls():
        results.append(discovered_idurls().pop(0))
    if _Debug:
        lg.out(_DebugLevel, 'lookup.consume_discovered_idurls : %s' % results)
    return results


def extract_discovered_idurls(count=1):
    if not discovered_idurls():
        if _Debug:
            lg.out(_DebugLevel, 'lookup.extract_discovered_idurls returns empty list')
        return []
    results = discovered_idurls()[:count]
    if _Debug:
        lg.out(_DebugLevel, 'lookup.extract_discovered_idurls : %s' % results)
    return results


# def schedule_next_lookup(current_lookup_task, delay=60):
#     global _NextLookupTask
#     if _NextLookupTask:
#         if _Debug:
#             lg.out(_DebugLevel, 'lookup.schedule_next_lookup SKIP, next lookup will start soon')
#         return
#     if _Debug:
#         lg.out(_DebugLevel, 'lookup.schedule_next_lookup after %d seconds' % delay)
#     _NextLookupTask = reactor.callLater(
#         delay,
#         start,
#         count=current_lookup_task.count,
#         consume=current_lookup_task.consume,
#         lookup_method=current_lookup_task.lookup_method,
#         observe_method=current_lookup_task.observe_method,
#         process_method=current_lookup_task.process_method
#     )


# def reset_next_lookup():
#     """
#     """
#     global _NextLookupTask
#     if _NextLookupTask and not _NextLookupTask.called and not _NextLookupTask.cancelled:
#         _NextLookupTask.cancel()
#         _NextLookupTask = None

#------------------------------------------------------------------------------

def start(count=1, consume=True, lookup_method=None, observe_method=None, process_method=None,):
    """
    NOTE: no parallel threads, DHT lookup can be started only one at time.
    """
    global _LookupTasks
    t = DiscoveryTask(
        count=count,
        consume=consume,
        lookup_method=lookup_method,
        observe_method=observe_method,
        process_method=process_method,
    )
    if len(discovered_idurls()) > count:
        if _Debug:
            lg.out(_DebugLevel - 4, 'lookup.start  knows %d discovered nodes, SKIP and return %d nodes' % (
                len(discovered_idurls()), count))
        if consume:
            idurls = consume_discovered_idurls(count)
        else:
            idurls = extract_discovered_idurls(count)
        reactor.callLater(0, t.result_defer.callback, idurls)
        return t
    _LookupTasks.append(t)
    reactor.callLater(0, work)
    # reset_next_lookup()
    if _Debug:
        lg.out(_DebugLevel - 4, 'lookup.start  new DiscoveryTask created for %d nodes' % count)
    return t

#------------------------------------------------------------------------------

def on_lookup_task_success(result):
    global _CurrentLookupTask
    if _Debug:
        lg.out(_DebugLevel - 4, 'lookup.on_lookup_task_success %s' % result)
    _CurrentLookupTask = None
    reactor.callLater(0, work)
    return result


def on_lookup_task_failed(err):
    global _CurrentLookupTask
    if _Debug:
        lg.out(_DebugLevel - 4, 'lookup.on_lookup_task_failed: %s' % err)
    _CurrentLookupTask = None
    reactor.callLater(0, work)
    return err


def work():
    """
    """
    global _CurrentLookupTask
    global _LookupTasks
    if _CurrentLookupTask:
        if _Debug:
            lg.out(_DebugLevel - 4, 'lookup.work SKIP, %s is in progress' % _CurrentLookupTask)
        return
    if not _LookupTasks:
        if _Debug:
            lg.out(_DebugLevel - 4, 'lookup.work SKIP no lookup tasks in the queue')
        return
    if _Debug:
        lg.out(_DebugLevel - 4, 'lookup.work starting next task in the queue')
    _CurrentLookupTask = _LookupTasks.pop(0)
    if not _CurrentLookupTask.result_defer:
        lg.warn('task %s is closed' % _CurrentLookupTask)
        return
    _CurrentLookupTask.start()
    if _CurrentLookupTask.result_defer:
        _CurrentLookupTask.result_defer.addCallback(on_lookup_task_success)
    else:
        lg.warn('task %s was closed imediately' % _CurrentLookupTask)

#------------------------------------------------------------------------------

class DiscoveryTask(object):

    def __init__(self,
                 count,
                 consume=True,
                 lookup_method=None,
                 observe_method=None,
                 process_method=None,):
        global _LookupMethod
        global _ObserveMethod
        global _ProcessMethod
        self.lookup_method = lookup_method or _LookupMethod
        self.observe_method = observe_method or _ObserveMethod
        self.process_method = process_method or _ProcessMethod
        self.started = time.time()
        self.count = count
        self.consume = consume
        self.succeed = 0
        self.failed = 0
        self.lookup_now = False
        self.stopped = False
        self.lookup_task = None
        self.result_defer = Deferred(canceller=lambda d: self._close())
        # self.result_defer = Deferred(canceller=lambda d: setattr(self, 'stopped', True))

    def __del__(self):
        if _Debug:
            lg.out(_DebugLevel, 'lookup.__del__')

    def start(self):
        if self.stopped:
            lg.warn('DiscoveryTask already stopped')
            return None
        if self.lookup_task and not self.lookup_task.called:
            lg.warn('lookup_nodes() method already called')
            return self.lookup_task
        if _Debug:
            lg.out(_DebugLevel, 'lookup.DiscoveryTask.start')
        return self._lookup_nodes()

    def stop(self):
        if _Debug:
            lg.out(_DebugLevel, 'lookup.DiscoveryTask.stop')
        self.stopped = True
        self._close()

    def _close(self):
        self.stopped = True
        if self.lookup_task and not self.lookup_task.called:
            self.lookup_task.cancel()
            self.lookup_task = None
        self.lookup_method = None
        self.observe_method = None
        self.process_method = None
        self.result_defer = None
        if _Debug:
            lg.out(_DebugLevel, 'lookup.close finished in %f seconds' % round(time.time() - self.started, 3))

    def _lookup_nodes(self):
        if _Debug:
            lg.out(_DebugLevel, 'lookup._lookup_nodes')
        if self.lookup_task and not self.lookup_task.called:
            if _Debug:
                lg.out(_DebugLevel, '    SKIP, already started')
            return self.lookup_task
        self.lookup_now = True
        self.lookup_task = self.lookup_method()
        self.lookup_task.addCallback(self._on_nodes_discovered)
        self.lookup_task.addErrback(self._on_lookup_failed)
        return self.lookup_task

    def _observe_nodes(self, nodes):
        if self.stopped:
            if _Debug:
                lg.warn('discovery process already stopped')
            return
        if _Debug:
            lg.out(_DebugLevel, 'lookup._observe_nodes on %d items' % len(nodes))
        observe_list = []
        for node in nodes:
            d = self.observe_method(node)
            d.addCallback(self._on_node_observed, node)
            d.addErrback(self._on_node_failed, node)
            observe_list.append(d)
        dl = DeferredList(observe_list, consumeErrors=False)
        dl.addCallback(self._on_all_nodes_observed)

    def _report_result(self, results=None):
        if _Debug:
            lg.out(_DebugLevel, 'lookup._report_result %s, result_defer=%s' % (str(results), self.result_defer))
        if results is None:
            if self.consume:
                results = consume_discovered_idurls(self.count)
                if _Debug:
                    lg.out(_DebugLevel, '    %d results consumed, %d were requested' % (len(results), self.count))
            else:
                results = extract_discovered_idurls(self.count)
                if _Debug:
                    lg.out(_DebugLevel, '    %d results extracted, %d were requested' % (len(results), self.count))
        if self.result_defer:
            self.result_defer.callback(results)
        self.result_defer = None

    def _report_fails(self, err):
        if _Debug:
            lg.out(_DebugLevel, 'lookup._report_fails %s' % err)
        if self.result_defer:
            self.result_defer.errback(err)
        self.result_defer = None

    def _on_node_succeed(self, node, info):
        self.succeed += 1
        if _Debug:
            lg.out(_DebugLevel, 'lookup._on_succeed %s info: %s' % (node, info))
        return node

    def _on_node_failed(self, err, arg=None):
        self.failed += 1
        if _Debug:
            lg.warn('%r : %r' % (arg, err))
        return None

    def _on_node_observed(self, idurl, node):
        if self.stopped:
            lg.warn('node observed, but discovery process already stopped')
            return None
        cached_time = known_idurls().get(idurl)
        if cached_time and time.time() - cached_time < 30.0:
            if _Debug:
                lg.out(_DebugLevel + 4, 'lookup._on_node_observed SKIP node %r already observed recently' % idurl)
            return None
        if _Debug:
            lg.out(_DebugLevel + 4, 'lookup._on_node_observed %r : %r' % (node, idurl))
        d = self.process_method(idurl, node)
        d.addErrback(self._on_node_failed, node)
        d.addCallback(self._on_identity_cached, node)
        return d

    def _on_node_processed(self, node, idurl):
        if _Debug:
            if len(discovered_idurls()) < self.count:
                lg.out(_DebugLevel, 'lookup._on_node_processed %s, but need more nodes' % idurl)
            else:
                lg.out(_DebugLevel, 'lookup._on_node_processed %s, have enough nodes now' % idurl)
        return node

    def _on_all_nodes_observed(self, observe_results):
        if self.stopped:
            lg.warn('_on_all_nodes_observed finished, but discovery process already stopped')
            return
        if _Debug:
            lg.out(_DebugLevel, 'lookup._on_all_nodes_observed results: %d, discovered nodes: %d' % (
                len(observe_results), len(discovered_idurls())))
#         results = []
#         for item in observe_results:
#             if item[0]:
#                 results.append(item[1])
#         if len(discovered_idurls()) == 0:
#             self._report_result([])
#             self._close()
#             return
        # if len(discovered_idurls()) < self.count:
        #     # self.lookup_task = self.lookup_nodes()
        #     self.start()
        #     return
        self._report_result()
        self._close()

    def _on_identity_cached(self, idurl, node):
        if self.stopped:
            return None
        if idurl is None:
            return None
        discovered_idurls().append(idurl)
        known_idurls()[idurl] = time.time()
        self._on_node_succeed(node, idurl)
        reactor.callLater(0, self._on_node_processed, node, idurl)
        if _Debug:
            lg.out(_DebugLevel, 'lookup._on_identity_cached : %s' % idurl)
        return idurl

    def _on_nodes_discovered(self, nodes):
        if _Debug:
            lg.out(_DebugLevel, 'lookup._on_nodes_discovered : %s, stopped=%s' % (str(nodes), self.stopped))
        self.lookup_now = False
        if self.stopped:
            lg.warn('on_nodes_discovered finished, but discovery process was already stopped')
            self._close()
            return None
        # if not nodes or len(discovered_idurls()) + len(nodes) < self.count:
            # self.lookup_task = self.lookup_nodes()
            # self.start()
        if not nodes:
            self._report_result()
            self._close()
            return None
        self._observe_nodes(nodes)
        return None

    def _on_lookup_failed(self, err):
        if _Debug:
            lg.out(_DebugLevel, 'lookup._on_lookup_failed %s' % err)
        self.lookup_now = False
        if self.stopped:
            lg.warn('discovery process already stopped')
            self._close()
            return
        self._report_fails(err)
        self._close()
        return err

#------------------------------------------------------------------------------
