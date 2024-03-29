#!/usr/bin/python
# encrypted.py
#
# Copyright (C) 2008-2018 Veselin Penev, https://bitdust.io
#
# This file (encrypted.py) is part of BitDust Software.
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
.. module:: encrypted.

Higher level code interfaces with ``encrypted`` so that it does not have to deal
with ECC stuff.  We write or read a large block at a time (maybe 64 MB say).
When writing we generate all the ECC information, and when reading we will
use ECC to recover lost information so user sees whole block still.

We have to go to disk. The normal mode is probably that there are a few machines that
are slow and the rest move along. We want to get the backup secure as soon as possible.
It can be secure even if 5 to 10 suppliers are not finished yet.  But this could be
a lot of storage, so we should be using disk.

We want to generate a pool of writes to do, and put in more as it gets below some
MB limit. But we should not be limited by a particular nodes speed.

The ``packet`` will have all the info about where it is going etc.
We number them with our block number and the supplier numbers.

Going to disk should let us do restarts after crashes without much trouble.

Digital signatures and timestamps are done on ``encrypted`` blocks of data.
Signatures are also done on ``packets`` and ``encrypted`` blocks.

RAIDMAKE:
    This object can be asked to generate any/all ``packet(s)`` that would come from this ``encrypted``.
RAIDREAD:
    It can also rebuild the ``encrypted`` from packets and will
    generate the read requests to get fetch the packets.
"""

#------------------------------------------------------------------------------

_Debug = False
_DebugLevel = 12

#------------------------------------------------------------------------------

from logs import lg

from lib import misc

from contacts import contactsdb

from userid import my_id

from crypt import key
from crypt import my_keys

#------------------------------------------------------------------------------


class Block:
    """
    A class to represent an encrypted Data block. The only 2 things secret in
    here will be the ``EncryptedSessionKey`` and ``EncryptedData``. Scrubbers
    may combine-packets/unserialize/inspect-blocks/check-signatures.

    CreatorID              http://cate.com/id1.xml  - so people can check signature - says PK type too
    BackupID               Creator's ID for the backup this packet is part of
    BlockNumber            number of this block
    EncryptedData          data may have some padding so multiple of crypto chunck size
                           and multiple of #nodes in eccmap (usually 64) for division
                           into packets
    Length                 real length of data when cleartext (encrypted may be padded)
    LastBlock              should now be "True" or "False" - careful in using
    SessionKeyType         which crypto is used for session key
    EncryptedSessionKey    encrypted with our public key so only we can read this
    Other                  could be be for professional timestamp company or other future features
    Signature              digital signature by Creator - verifiable by public key in creator identity
    """

    def __init__(self,
                 CreatorID=None,
                 BackupID='',
                 BlockNumber=0,
                 SessionKey='',
                 SessionKeyType=None,
                 LastBlock=True,
                 Data='',
                 EncryptKey=None,
                 DecryptKey=None, ):
        self.CreatorID = CreatorID
        if not self.CreatorID:
            self.CreatorID = my_id.getLocalID()
        self.BackupID = str(BackupID)
        self.BlockNumber = BlockNumber
        if callable(EncryptKey):
            self.EncryptedSessionKey = EncryptKey(SessionKey)
        elif isinstance(EncryptKey, basestring):
            self.EncryptedSessionKey = my_keys.encrypt(EncryptKey, SessionKey)
        else:
            self.EncryptedSessionKey = key.EncryptLocalPublicKey(SessionKey)
        self.SessionKeyType = SessionKeyType
        if not self.SessionKeyType:
            self.SessionKeyType = key.SessionKeyType()
        self.Length = len(Data)
        self.LastBlock = bool(LastBlock)
        self.EncryptedData = key.EncryptWithSessionKey(SessionKey, Data)  # DataLonger
        self.Signature = None
        self.Sign()
        self.DecryptKey = DecryptKey
        if _Debug:
            lg.out(_DebugLevel, 'new data in %s' % self)

    def __repr__(self):
        return 'encrypted{ BackupID=%s BlockNumber=%s Length=%s LastBlock=%s }' % (str(self.BackupID), str(self.BlockNumber), str(self.Length), self.LastBlock)

    def SessionKey(self):
        """
        Return original SessionKey from ``EncryptedSessionKey`` using one of the methods
        depend on the type of ``DecryptKey`` parameter passed in the __init__()

            + ``crypt.key.DecryptLocalPrivateKey()`` if DecryptKey is None
            + ``my_keys.decrypt()`` if DecryptKey is a string with key_id
            + ``DecryptKey()`` if this is a callback method
        """
        if callable(self.DecryptKey):
            return self.DecryptKey(self.EncryptedSessionKey)
        elif isinstance(self.DecryptKey, basestring):
            return my_keys.decrypt(self.DecryptKey, self.EncryptedSessionKey)
        return key.DecryptLocalPrivateKey(self.EncryptedSessionKey)

    def GenerateHashBase(self):
        """
        Generate a single string with all data fields, used to create a hash
        for that ``encrypted_block``.
        """
        sep = "::::"
        StringToHash = self.CreatorID
        StringToHash += sep + self.BackupID
        StringToHash += sep + str(self.BlockNumber)
        StringToHash += sep + self.SessionKeyType
        StringToHash += sep + self.EncryptedSessionKey
        StringToHash += sep + str(self.Length)
        StringToHash += sep + str(self.LastBlock)
        StringToHash += sep + self.EncryptedData
        return StringToHash

    def GenerateHash(self):
        """
        Create a hash for that ``encrypted_block`` using ``crypt.key.Hash()``.
        """
        return key.Hash(self.GenerateHashBase())

    def Sign(self):
        """
        Generate digital signature for that ``encrypted_block``.
        """
        self.Signature = self.GenerateSignature()  # usually just done at packet creation
        return self

    def GenerateSignature(self):
        """
        Call ``crypt.key.Sign()`` to generate signature.
        """
        return key.Sign(self.GenerateHash())

    def Ready(self):
        """
        Just return True if signature is already created.
        """
        return self.Signature is not None

    def Valid(self):
        """
        Validate signature to verify the ``encrypted_block``.
        """
        if not self.Ready():
            # lg.warn("block is not ready yet " + str(self))
            lg.warn("block is not ready yet " + str(self))
            return False
        hashsrc = self.GenerateHash()
        ConIdentity = contactsdb.get_contact_identity(my_id.getLocalID())
        if ConIdentity is None:
            lg.warn("could not get Identity so returning False")
            return False
        result = key.Verify(ConIdentity, hashsrc, self.Signature)    # At block level only work on own stuff
        return result

    def Data(self):
        """
        Return an original data, decrypt using ``EncryptedData`` and
        ``EncryptedSessionKey``.
        """
        SessionKey = self.SessionKey()
        ClearLongData = key.DecryptWithSessionKey(SessionKey, self.EncryptedData)
        return ClearLongData[0:self.Length]    # remove padding

    def Serialize(self):
        """
        Create a string that stores all data fields of that ``encrypted.Block``
        object.
        """
        decrypt_key = getattr(self, 'DecryptKey')
        delattr(self, 'DecryptKey')
        e = misc.ObjectToString(self)
        setattr(self, 'DecryptKey', decrypt_key)
        return e

#------------------------------------------------------------------------------


def Unserialize(data, decrypt_key=None):
    """
    A method to create a ``encrypted.Block`` instance from input string.
    """
    newobject = misc.StringToObject(data)
    setattr(newobject, 'DecryptKey', decrypt_key)
    return newobject
