#!/usr/bin/env python
# nickname_holder.py
#
# Copyright (C) 2008-2018 Veselin Penev, https://bitdust.io
#
# This file (nickname_holder.py) is part of BitDust Software.
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


"""
.. module:: nickname_holder

.. role:: red


BitDust nickname_holder() Automat

.. raw:: html

    <a href="nickname_holder.png" target="_blank">
    <img src="nickname_holder.png" style="max-width:100%;">
    </a>

EVENTS:
    * :red:`dht-erase-failed`
    * :red:`dht-erase-success`
    * :red:`dht-read-failed`
    * :red:`dht-read-success`
    * :red:`dht-write-failed`
    * :red:`dht-write-success`
    * :red:`set`
    * :red:`timer-5min`
"""

#------------------------------------------------------------------------------

import sys

from logs import lg

from automats import automat

from main import settings

from userid import my_id

from dht import dht_service
from dht import dht_records

#------------------------------------------------------------------------------

_NicknameHolder = None

#------------------------------------------------------------------------------


def A(event=None, arg=None):
    """
    Access method to interact with the state machine.
    """
    global _NicknameHolder
    if _NicknameHolder is None:
        # set automat name and starting state here
        _NicknameHolder = NicknameHolder('nickname_holder', 'AT_STARTUP', 4, True)
    if event is not None:
        _NicknameHolder.automat(event, arg)
    return _NicknameHolder


def Destroy():
    """
    Destroy nickname_holder() automat and remove its instance from memory.
    """
    global _NicknameHolder
    if _NicknameHolder is None:
        return
    _NicknameHolder.destroy()
    del _NicknameHolder
    _NicknameHolder = None

#------------------------------------------------------------------------------


class NicknameHolder(automat.Automat):
    """
    This class implements all the functionality of the ``nickname_holder()``
    state machine.
    """

    timers = {
        'timer-5min': (300, ['READY']),
    }

    def init(self):
        """
        Method to initialize additional variables and flags at creation of the
        state machine.
        """
        self.nickname = None
        self.key = None
        self.dht_read_defer = None
        self.result_callbacks = []

    def add_result_callback(self, cb):
        self.result_callbacks.append(cb)

    def remove_result_callback(self, cb):
        self.result_callbacks.remove(cb)

    def A(self, event, arg):
        #---AT_STARTUP---
        if self.state == 'AT_STARTUP':
            if event == 'set':
                self.state = 'DHT_READ'
                self.Attempts = 0
                self.doSetNickname(arg)
                self.doMakeKey(arg)
                self.doDHTReadKey(arg)
        #---READY---
        elif self.state == 'READY':
            if event == 'timer-5min':
                self.state = 'DHT_READ'
                self.doSetNickname(arg)
                self.doMakeKey(arg)
                self.doDHTReadKey(arg)
            elif event == 'set':
                self.state = 'DHT_ERASE'
                self.doDHTEraseKey(arg)
                self.doSetNickname(arg)
        #---DHT_READ---
        elif self.state == 'DHT_READ':
            if event == 'dht-read-success' and self.isMyOwnKey(arg):
                self.state = 'READY'
                self.doReportNicknameOwn(arg)
            elif event == 'dht-read-failed':
                self.state = 'DHT_WRITE'
                self.doDHTWriteKey(arg)
            elif event == 'dht-read-success' and not self.isMyOwnKey(arg):
                self.doReportNicknameExist(arg)
                self.doNextKey(arg)
                self.doDHTReadKey(arg)
            elif event == 'set':
                self.doSetNickname(arg)
                self.doMakeKey(arg)
                self.doDHTReadKey(arg)
        #---DHT_WRITE---
        elif self.state == 'DHT_WRITE':
            if event == 'dht-write-failed' and self.Attempts > 5:
                self.state = 'READY'
                self.Attempts = 0
                self.doReportNicknameFailed(arg)
            elif event == 'dht-write-failed' and self.Attempts <= 5:
                self.state = 'DHT_READ'
                self.Attempts += 1
                self.doNextKey(arg)
                self.doDHTReadKey(arg)
            elif event == 'dht-write-success':
                self.state = 'READY'
                self.Attempts = 0
                self.doReportNicknameRegistered(arg)
            elif event == 'set':
                self.state = 'DHT_READ'
                self.doSetNickname(arg)
                self.doMakeKey(arg)
                self.doDHTReadKey(arg)
        #---DHT_ERASE---
        elif self.state == 'DHT_ERASE':
            if event == 'dht-erase-success' or event == 'dht-erase-failed':
                self.state = 'DHT_READ'
                self.doMakeKey(arg)
                self.doDHTReadKey(arg)
            elif event == 'set':
                self.state = 'DHT_READ'
                self.doSetNickname(arg)
                self.doMakeKey(arg)
                self.doDHTReadKey(arg)
        return None

    def isMyOwnKey(self, arg):
        """
        Condition method.
        """
        return arg == my_id.getLocalID()

    def doSetNickname(self, arg):
        """
        Action method.
        """
        self.nickname = arg or \
            settings.getNickName() or \
            my_id.getLocalIdentity().getIDName()
        settings.setNickName(self.nickname)

    def doMakeKey(self, arg):
        """
        Action method.
        """
        # self.key = self.nickname + ':' + '0'
        self.key = dht_service.make_key(
            key=self.nickname,
            index=0,
            prefix='nickname',
        )

    def doNextKey(self, arg):
        """
        Action method.
        """
        try:
            key_info = dht_service.split_key(self.key)
            # nik, number = self.key.rsplit(':', 1)
            index = int(key_info['index'])
        except:
            lg.exc()
            index = 0
        index += 1
        # self.key = self.nickname + ':' + str(index)
        self.key = dht_service.make_key(
            key=self.nickname,
            index=index,
            prefix='nickname',
        )

    def doDHTReadKey(self, arg):
        """
        Action method.
        """
        if self.dht_read_defer is not None:
            self.dht_read_defer.pause()
            self.dht_read_defer.cancel()
            self.dht_read_defer = None
        d = dht_records.get_nickname(self.key)
        d.addCallback(self._dht_read_result, self.key)
        d.addErrback(self._dht_read_failed)
        self.dht_read_defer = d

    def doDHTWriteKey(self, arg):
        """
        Action method.
        """
        d = dht_records.set_nickname(self.key, my_id.getLocalID())
        d.addCallback(self._dht_write_result)
        d.addErrback(lambda x: self.automat('dht-write-failed'))

    def doDHTEraseKey(self, arg):
        """
        Action method.
        """
        d = dht_service.delete_key(self.key)
        d.addCallback(self._dht_erase_result)
        d.addErrback(lambda x: self.automat('dht-erase-failed'))

    def doReportNicknameOwn(self, arg):
        """
        Action method.
        """
        lg.out(8, 'nickname_holder.doReportNicknameOwn : %s with %s' % (self.key, arg, ))
        for cb in self.result_callbacks:
            cb('my own', self.key)

    def doReportNicknameRegistered(self, arg):
        """
        Action method.
        """
        lg.out(8, 'nickname_holder.doReportNicknameRegistered : %s with %s' % (self.key, arg, ))
        for cb in self.result_callbacks:
            cb('registered', self.key)

    def doReportNicknameExist(self, arg):
        """
        Action method.
        """
        lg.out(8, 'nickname_holder.doReportNicknameExist : %s with %s' % (self.key, arg, ))
        for cb in self.result_callbacks:
            cb('exist', self.key)

    def doReportNicknameFailed(self, arg):
        """
        Action method.
        """
        lg.out(8, 'nickname_holder.doReportNicknameFailed : %s with %s' % (self.key, arg, ))
        for cb in self.result_callbacks:
            cb('failed', self.key)

    def _dht_read_result(self, value, key):
        self.dht_read_defer = None
        try:
            v = value['idurl']
        except:
            lg.out(8, '%r' % value)
            lg.exc()
            self.automat('dht-read-failed')
            return
        self.automat('dht-read-success', v)

    def _dht_read_failed(self, x):
        self.dht_read_defer = None
        self.automat('dht-read-failed', x)

    def _dht_write_result(self, nodes):
        if len(nodes) > 0:
            self.automat('dht-write-success')
        else:
            self.automat('dht-write-failed')

    def _dht_erase_result(self, result):
        if result is None:
            self.automat('dht-erase-failed')
        else:
            self.automat('dht-erase-success')

#------------------------------------------------------------------------------


def main():
    from twisted.internet import reactor
    lg.set_debug_level(24)
    settings.init()
    my_id.init()
    dht_service.init(settings.getDHTPort())
    reactor.callWhenRunning(A, 'init', sys.argv[1])
    reactor.run()


if __name__ == "__main__":
    main()
