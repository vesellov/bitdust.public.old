#!/usr/bin/python
# my_id.py
#
# Copyright (C) 2008-2018 Veselin Penev, https://bitdust.io
#
# This file (my_id.py) is part of BitDust Software.
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

module:: my_id
"""

import os
import sys
import string
import time

#------------------------------------------------------------------------------

if __name__ == '__main__':
    import os.path as _p
    sys.path.insert(0, _p.abspath(_p.join(_p.dirname(_p.abspath(sys.argv[0])), '..')))

#------------------------------------------------------------------------------

from logs import lg

from system import bpio

from main import settings
from main import events

from lib import misc
from lib import nameurl

from crypt import key

from userid import identity

#------------------------------------------------------------------------------

_LocalIdentity = None
_LocalIDURL = None
_LocalName = None
_ValidTransports = ['tcp', 'udp', 'http', 'proxy', ]

#------------------------------------------------------------------------------


def init():
    """
    Will be called in main thread at start up.

    Can put here some minor things if needed.
    """
    lg.out(4, 'my_id.init')
    loadLocalIdentity()


def shutdown():
    lg.out(4, 'my_id.shutdown')
    forgetLocalIdentity()

#-------------------------------------------------------------------------------


def isLocalIdentityReady():
    """
    Return True if local identity object already initialized and stored in
    memory.
    """
    global _LocalIdentity
    return _LocalIdentity is not None


def setLocalIdentity(ident):
    """
    Set local identity object in the memory.
    """
    global _LocalIdentity
    global _LocalIDURL
    global _LocalName
    if not ident:
        return
    modified = False
    old_json = {}
    if _LocalIdentity:
        current_src = _LocalIdentity.serialize()
        if current_src != ident.serialize():
            modified = True
            old_json = _LocalIdentity.serialize_json()
    _LocalIdentity = ident
    _LocalIDURL = _LocalIdentity.getIDURL()
    _LocalName = _LocalIdentity.getIDName()
    if modified:
        events.send('local-identity-modified', dict(old=old_json, new=_LocalIdentity.serialize_json()))


def setLocalIdentityXML(idxml):
    """
    Construct identity object from XML string and save it to the memory.
    """
    setLocalIdentity(identity.identity(xmlsrc=idxml))


def getLocalIdentity():
    """
    Return my identity object.
    """
    global _LocalIdentity
    if not isLocalIdentityReady():
        loadLocalIdentity()
    return _LocalIdentity


def getLocalID():
    """
    Return my IDURL. Deprecated, use getLocalIDURL().
    """
    global _LocalIDURL
    if _LocalIDURL is None:
        localIdent = getLocalIdentity()
        if localIdent:
            _LocalIDURL = localIdent.getIDURL()
    return _LocalIDURL


def getLocalIDURL():
    """
    Return my IDURL.
    """
    # just an alias for now
    # TODO: deprecate getLocalID() in favor of getLocalIDURL()
    return getLocalID()


def getIDName():
    """
    Return my account name, this is a filename part of IDURL without '.xml'.
    """
    global _LocalName
    if _LocalName is None:
        localIdent = getLocalIdentity()
        if localIdent:
            _LocalName = localIdent.getIDName()
    return _LocalName


def getGlobalID(key_alias=None):
    """
    Return my global user id - according to my current IDURL.
    """
    from userid import global_id
    glob_id = global_id.UrlToGlobalID(getLocalID())
    if key_alias:
        glob_id = '{}${}'.format(key_alias, glob_id)
    return glob_id

#------------------------------------------------------------------------------


def loadLocalIdentity():
    """
    The core method.

    The file [BitDust data dir]/metadata/localidentity keeps the user
    identity in XML format. Do read the local file and set into object
    in memory.
    """
    global _LocalIdentity
    global _LocalIDURL
    global _LocalName
    xmlid = ''
    filename = bpio.portablePath(settings.LocalIdentityFilename())
    if os.path.exists(filename):
        xmlid = bpio.ReadTextFile(filename)
        lg.out(6, 'my_id.loadLocalIdentity %d bytes read from\n        %s' % (len(xmlid), filename))
    if xmlid == '':
        lg.out(2, "my_id.loadLocalIdentity SKIPPED, local identity in %s is EMPTY !!!" % filename)
        return
    lid = identity.identity(xmlsrc=xmlid)
    if not lid.isCorrect():
        lg.out(2, "my_id.loadLocalIdentity ERROR loaded identity is not Correct")
        return
    if not lid.Valid():
        lg.out(2, "my_id.loadLocalIdentity ERROR loaded identity is not Valid")
        return
    setLocalIdentity(lid)
#     _LocalIdentity = lid
#     _LocalIDURL = lid.getIDURL()
#     _LocalName = lid.getIDName()
    setTransportOrder(getOrderFromContacts(_LocalIdentity))
    lg.out(6, "my_id.loadLocalIdentity my name is [%s]" % lid.getIDName())


def saveLocalIdentity():
    """
    Save identity object from memory into local file.

    Do sign the identity than serialize to write to the file.
    """
    global _LocalIdentity
    if not isLocalIdentityReady():
        lg.warn("ERROR local identity not exist!")
        return
    if not _LocalIdentity.isCorrect():
        lg.warn('local identity is not correct')
        return
    _LocalIdentity.sign()
    xmlid = _LocalIdentity.serialize()
    filename = bpio.portablePath(settings.LocalIdentityFilename())
    bpio.WriteFile(filename, xmlid)
    lg.out(6, "my_id.saveLocalIdentity %d bytes wrote to %s" % (len(xmlid), filename))


def forgetLocalIdentity():
    """
    """
    global _LocalIdentity
    if not isLocalIdentityReady():
        lg.out(2, "my_id.forgetLocalIdentity ERROR localidentity not exist!")
        return
    lg.out(6, "my_id.saveLocalIdentity")
    _LocalIdentity = None
    events.send('local-identity-deleted', dict())


def eraseLocalIdentity():
    filename = bpio.portablePath(settings.LocalIdentityFilename())
    if not os.path.exists(filename):
        lg.out(6, "my_id.eraseLocalIdentity SKIP file %s not exist" % filename)
        return True
    if not os.path.isfile(filename):
        lg.out(6, "my_id.eraseLocalIdentity ERROR path %s is not a file" % filename)
        return False
    try:
        os.remove(filename)
    except:
        lg.exc()
        return False
    lg.out(6, "my_id.eraseLocalIdentity file %s was deleted" % filename)
    return True

#------------------------------------------------------------------------------


def getValidTransports():
    """
    """
    global _ValidTransports
    return _ValidTransports


def isValidTransport(transport):
    """
    Check string to be a valid transport.

    See ``lib.transport_control' for more details.
    """
    global _ValidTransports
    if transport in _ValidTransports:
        return True
    else:
        return False


def validateTransports(orderL):
    """
    Validate a list of strings - all must be a valid transports.
    """
    global _ValidTransports
    transports = []
    for transport in orderL:
        if isValidTransport(transport):
            transports.append(transport)
        else:
            lg.warn('invalid entry in transport list: %s , ignored' % str(transport))
    if len(transports) == 0:
        lg.out(1, 'my_id.validateTransports ERROR no valid transports, using default transports ' + str(_ValidTransports))
        transports = _ValidTransports
#    if len(transports) != len(orderL):
#        lg.out(1, 'my_id.validateTransports ERROR Transports contained an invalid entry, need to figure out where it came from.')
    return transports


def setTransportOrder(orderL):
    """
    Validate transports and save the list in the [BitDust data
    dir]\metadata\torder.

    It is useful to remember the priority of used transports.
    """
    orderl = orderL
    orderL = validateTransports(orderL)
    orderTxt = string.join(orderl, ' ')
    lg.out(8, 'my_id.setTransportOrder: ' + str(orderTxt))
    bpio.WriteFile(settings.DefaultTransportOrderFilename(), orderTxt)


def getTransportOrder():
    """
    Read and validate tranports from [BitDust data dir]\metadata\torder file.
    """
    global _ValidTransports
    lg.out(8, 'my_id.getTransportOrder')
    order = bpio.ReadTextFile(settings.DefaultTransportOrderFilename()).strip()
    if order == '':
        orderL = _ValidTransports
    else:
        orderL = order.split(' ')
        orderL = validateTransports(orderL)
    setTransportOrder(orderL)
    return orderL


def getOrderFromContacts(ident):
    """
    A wrapper for ``identity.getProtoOrder`` method.
    """
    return ident.getProtoOrder()

#------------------------------------------------------------------------------


def buildProtoContacts(id_obj, skip_transports=[]):
    """
    Create a full list of needed transport methods to be able to accept
    incoming traffic from other nodes.

    Make calls to transport services to build a list of my contacts.
    """
    from services import driver
    # prepare contacts
    current_contats = id_obj.getContactsByProto()
    current_order = id_obj.getProtoOrder()
    lg.out(4, 'my_id.buildProtoContacts')
    lg.out(4, '    current contacts: %s' % str(current_contats))
    lg.out(4, '    current order: %s' % str(current_order))
    new_contacts = {}
    new_order_correct = []
    # prepare list of active transports
    active_transports = []
    for proto in getValidTransports():
        if proto in skip_transports:
            continue
        if not settings.transportIsEnabled(proto):
            continue
        if not settings.transportReceivingIsEnabled(proto):
            continue
        if not driver.is_on('service_%s_transport' % proto):
            lg.warn('transport "%s" is enabled, but service_%s_transport() is not ready yet' % (proto, proto))
            continue
        active_transports.append(proto)
    # sort active transports by priority
    lg.out(4, '    active transports: %s' % str(active_transports))
    active_transports.sort(key=settings.getTransportPriority)
    lg.out(4, '    sorted transports: %s' % str(active_transports))
    if not driver.is_on('service_gateway'):
        new_contacts = current_contats
        new_order_correct = current_order
    else:
        from transport import gateway
        # build contacts data according transports priorities
        new_order = current_order
        for proto in active_transports:
            clist = gateway.transport(proto).interface.build_contacts(id_obj)
            cdict = {}
            corder = []
            for contact in clist:
                cproto, cdata = contact.split('://')
                cdict[cproto] = contact
                corder.append(cproto)
            new_contacts.update(cdict)
            for cproto in corder:
                if cproto not in new_order:
                    new_order.append(cproto)
        new_order_correct = list(new_order)
        for nproto in new_order:
            if nproto not in new_contacts.keys():
                new_order_correct.remove(nproto)

#            cset = set(corder)
#            cdiff = cset.intersection(current_set)
#            if cset.isdisjoint()
#
#
#            if len(clist) > 1:
#                # clist.reverse()
#                for contact in clist:
#                    cproto, cdata = contact.split('://')
#                    cdict[cproto] = contact
#                    if cproto in new_order:
#                        new_order.remove(cproto)
#                    new_order.insert(0, cproto)
#            else:
##                 current_order = []
#                for contact in clist:
#                    cproto, cdata = contact.split('://')
#                    cdict[cproto] = contact
# current_order.append(cproto)
#                    new_index = -1
#                    if cproto in new_order:
#                        new_index = new_order.index(cproto)
#                    old_index = -1
#                    if cproto in current_order:
#                        old_index =  current_order.index(cproto)
#                    if new_index < 0:
#                        new_order.insert(0, cproto)
#                    else:
#                        if old_index < new_index:
#                            new_order.remove(cproto)
#                            new_order.insert(0, cproto)
#                        else:
#                            new_order.remove(cproto)
#                            new_order.append(cproto)
#            new_contacts.update(cdict)

    lg.out(4, '    new contacts: %s' % str(new_contacts))
    lg.out(4, '    new order: %s' % str(new_order_correct))

#    new_list = []
#    for nproto in new_order_correct:
#        new_list.append(new_contacts[nproto])

    return new_contacts, new_order_correct


def buildDefaultIdentity(name='', ip='', idurls=[]):
    """
    Use some local settings and config files to create some new identity.

    Nice to provide a user name or it will have a form like: [ip
    address]_[date].
    """
    if ip == '':
        ip = misc.readExternalIP()  # bpio.ReadTextFile(settings.ExternalIPFilename())
    if name == '':
        name = ip.replace('.', '-') + '_' + time.strftime('%M%S')
    lg.out(4, 'my_id.buildDefaultIdentity: %s %s' % (name, ip))
    # create a new identity object
    # it is stored in memory and another copy on disk drive
    ident = identity.identity(xmlsrc=identity.default_identity_src)
    # this is my IDURL address
    # you can have many IDURL locations for same identity
    # just need to keep all them synchronized
    # this is identity propagate procedure, see p2p/propagate.py
    if len(idurls) == 0:
        idurls.append('http://localhost/' + name.lower() + '.xml')
    for idurl in idurls:
        ident.sources.append(idurl.encode("ascii").strip())
    # create a full list of needed transport methods
    # to be able to accept incoming traffic from other nodes
    new_contacts, new_order = buildProtoContacts(ident)
    if len(new_contacts) == 0:
        if settings.enableTCP() and settings.enableTCPreceiving():
            new_contacts['tcp'] = 'tcp://' + ip + ':' + str(settings.getTCPPort())
            new_order.append('tcp')
        if settings.enableUDP() and settings.enableUDPreceiving():
            x, servername, x, x = nameurl.UrlParse(ident.sources[0])
            new_contacts['udp'] = 'udp://%s@%s' % (name.lower(), servername)
            new_order.append('udp')
        if settings.enableHTTP() and settings.enableHTTPreceiving():
            new_contacts['http'] = 'http://' + ip + ':' + str(settings.getHTTPPort())
            new_order.append('http')
    # erase current contacts from my identity
    ident.clearContacts()
    # add contacts data to the local identity
    for proto in new_order:
        contact = new_contacts.get(proto, None)
        if contact is None:
            lg.warn('proto %s was not found in contacts' % proto)
            continue
        ident.setProtoContact(proto, contact)
    # set other info
    ident.certificates = []
    ident.date = time.strftime('%b %d, %Y')
    ident.postage = "1"
    ident.revision = "0"
    ident.version = ""  # TODO: put latest git commit hash here
    # update software version number
    # version_number = bpio.ReadTextFile(settings.VersionNumberFile()).strip()
    # repo, location = misc.ReadRepoLocation()
    # ident.version = (version_number.strip() + ' ' + repo.strip() + ' ' + bpio.osinfo().strip()).strip()
    # build a version info
    # vernum = bpio.ReadTextFile(settings.VersionNumberFile())
    # repo, location = misc.ReadRepoLocation()
    # ident.version = (vernum.strip() + ' ' + repo.strip() + ' ' + bpio.osinfo().strip()).strip()
    # put my public key in my identity
    ident.publickey = key.MyPublicKey()
    # generate signature
    ident.sign()
    # validate new identity
    if not ident.Valid():
        lg.warn('generated identity is not valid !!!')
    return ident


def rebuildLocalIdentity(skip_transports=[]):
    """
    If some transports was enabled or disabled we want to update identity
    contacts. Just empty all of the contacts and create it again in the same
    order.

    Also increase revision number by one - others may keep track of my modifications.
    """
    # getting current copy of local identity
    lid = getLocalIdentity()
    # remember the current identity - full XML source code
    current_identity_xmlsrc = lid.serialize()
    lg.out(4, 'my_id.rebuildLocalIdentity current identity is %d bytes long' % len(current_identity_xmlsrc))
    # create a full list of needed transport methods
    # to be able to accept incoming traffic from other nodes
    new_contacts, new_order = buildProtoContacts(lid, skip_transports=skip_transports)
    # erase current contacts from my identity
    lid.clearContacts()
    # add contacts data to the local identity
    lid.setContactsFromDict(new_contacts, new_order)
#    for proto in new_order:
#        contact = new_contacts.get(proto, None)
#        if contact is None:
#            lg.warn('proto %s was not found in contacts' % proto)
#            continue
#        lid.setProtoContact(proto, contact)
    # update software version number
    vernum = bpio.ReadTextFile(settings.VersionNumberFile())
    repo, _ = misc.ReadRepoLocation()
    lid.version = (vernum.strip() + ' ' + repo.strip() + ' ' + bpio.osinfo().strip()).strip()
    # generate signature with changed content
    lid.sign()
    new_xmlsrc = lid.serialize()
    changed = False
    if new_xmlsrc == current_identity_xmlsrc:
        # no modifications in my identity - cool !!!
        lg.out(4, '    same revision: %s' % lid.revision)
    else:
        try:
            lid.revision = str(int(lid.revision) + 1)
        except:
            lg.exc()
            return False
        # generate signature again because revision were changed !!!
        lid.sign()
        lg.out(4, '    add revision: %s' % lid.revision)
        changed = True
        # remember the new identity
        setLocalIdentity(lid)
    lg.out(4, '    version: %s' % str(lid.version))
    lg.out(4, '    contacts: %s' % str(lid.contacts))
    lg.out(4, '    sources: %s' % str(lid.sources))
    if changed:
        lg.out(4, '    SAVING new identity #%s' % lid.revision)
        # finally saving modified local identity
        saveLocalIdentity()
    lg.out(4, '    my identity HAS %sBEEN changed !!!' % (('' if changed else 'NOT ')))
    lg.out(4, '\n' + new_xmlsrc + '\n')
    return changed
