#!/usr/bin/python
# service_shared_data.py
#
# Copyright (C) 2008-2018 Veselin Penev, https://bitdust.io
#
# This file (service_shared_data.py) is part of BitDust Software.
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

module:: service_shared_data
"""

from services.local_service import LocalService


def create_service():
    return SharedDataService()


class SharedDataService(LocalService):

    service_name = 'service_shared_data'
    config_path = 'services/shared-data/enabled'

    def dependent_on(self):
        return ['service_restores',
                ]

    def start(self):
        from main import events
        from transport import callback
        callback.append_inbox_callback(self._on_inbox_packet_received)
        events.add_subscriber(self._on_supplier_modified, 'supplier-modified')
        return True

    def stop(self):
        from main import events
        from transport import callback
        events.remove_subscriber(self._on_supplier_modified)
        callback.remove_inbox_callback(self._on_inbox_packet_received)
        return True

    def _on_supplier_modified(self, evt):
        from access import key_ring
        from crypt import my_keys
        from userid import global_id
        from userid import my_id
        if evt.data['new_idurl']:
            my_keys_to_be_republished = []
            for key_id in my_keys.known_keys():
                if not key_id.startswith('share_'):
                    continue
                _glob_id = global_id.ParseGlobalID(key_id)
                if _glob_id['idurl'] == my_id.getLocalIDURL():
                    my_keys_to_be_republished.append(key_id)
            for key_id in my_keys_to_be_republished:
                key_ring.transfer_key(key_id, trusted_idurl=evt.data['new_idurl'], include_private=False)

    def _on_inbox_packet_received(self, newpacket, info, status, error_message):
        from p2p import commands
        if newpacket.Command == commands.Files():
            return self._on_files_received(newpacket, info)
        return False

    def _on_files_received(self, newpacket, info):
        import json
        from logs import lg
        from main import settings
        from main import events
        from p2p import p2p_service
        from storage import backup_fs
        from storage import backup_control
        from crypt import encrypted
        from crypt import my_keys
        from userid import my_id
        from userid import global_id
        from storage import backup_matrix
        from supplier import list_files
        from contacts import contactsdb
        list_files_global_id = global_id.ParseGlobalID(newpacket.PacketID)
        if not list_files_global_id['idurl']:
            lg.warn('invalid PacketID: %s' % newpacket.PacketID)
            return False
        trusted_customer_idurl = list_files_global_id['idurl']
        incoming_key_id = list_files_global_id['key_id']
        if trusted_customer_idurl == my_id.getGlobalID():
            lg.warn('skip %s packet which seems to came from my own supplier' % newpacket)
            # only process list Files() from other users who granted me access
            return False
        if not my_keys.is_valid_key_id(incoming_key_id):
            lg.warn('ignore, invalid key id in packet %s' % newpacket)
            return False
        if not my_keys.is_key_private(incoming_key_id):
            lg.warn('private key is not registered : %s' % incoming_key_id)
            p2p_service.SendFail(newpacket, 'private key is not registered')
            return False
        try:
            block = encrypted.Unserialize(
                newpacket.Payload,
                decrypt_key=incoming_key_id,
            )
        except:
            lg.exc(newpacket.Payload)
            return False
        if block is None:
            lg.warn('failed reading data from %s' % newpacket.RemoteID)
            return False
#         if block.CreatorID != trusted_customer_idurl:
#             lg.warn('invalid packet, creator ID must be present in packet ID : %s ~ %s' % (
#                 block.CreatorID, list_files_global_id['idurl'], ))
#             return False
        try:
            raw_files = block.Data()
        except:
            lg.exc()
            return False
        if block.CreatorID == trusted_customer_idurl:
            # this is a trusted guy sending some shared files to me
            try:
                json_data = json.loads(raw_files, encoding='utf-8')
                json_data['items']
            except:
                lg.exc()
                return False
            count = backup_fs.Unserialize(
                raw_data=json_data,
                iter=backup_fs.fs(trusted_customer_idurl),
                iterID=backup_fs.fsID(trusted_customer_idurl),
                from_json=True,
            )
            p2p_service.SendAck(newpacket)
            events.send('shared-list-files-received', dict(
                customer_idurl=trusted_customer_idurl,
                new_items=count,
            ))
            if count == 0:
                lg.warn('no files were imported during file sharing')
            else:
                backup_control.Save()
                lg.info('imported %d shared files from %s, key_id=%s' % (
                    count, trusted_customer_idurl, incoming_key_id, ))
            return True
        # otherwise this must be an external supplier sending us a files he stores for trusted customer
        external_supplier_idurl = block.CreatorID
        try:
            supplier_raw_list_files = list_files.UnpackListFiles(raw_files, settings.ListFilesFormat())
            backup_matrix.SaveLatestRawListFiles(
                supplier_idurl=external_supplier_idurl,
                raw_data=supplier_raw_list_files,
                customer_idurl=trusted_customer_idurl,
            )
        except:
            lg.exc()
            return False
        # need to detect supplier position from the list of packets
        # and place that supplier on the correct position in contactsdb
        real_supplier_pos = backup_matrix.DetectSupplierPosition(supplier_raw_list_files)
        known_supplier_pos = contactsdb.supplier_position(external_supplier_idurl, trusted_customer_idurl)
        if real_supplier_pos >= 0:
            if known_supplier_pos >= 0 and known_supplier_pos != real_supplier_pos:
                lg.warn('external supplier %s position is not matching to list files, rewriting for customer %s' % (
                    external_supplier_idurl, trusted_customer_idurl))
                contactsdb.erase_supplier(
                    idurl=external_supplier_idurl,
                    customer_idurl=trusted_customer_idurl,
                )
            contactsdb.add_supplier(
                idurl=external_supplier_idurl,
                position=real_supplier_pos,
                customer_idurl=trusted_customer_idurl,
            )
            contactsdb.save_suppliers(customer_idurl=trusted_customer_idurl)
        else:
            lg.warn('not possible to detect external supplier position for customer %s' % trusted_customer_idurl)
        # finally send ack packet back
        p2p_service.SendAck(newpacket)
        lg.info('received list of packets from external supplier %s for customer %s' % (external_supplier_idurl, trusted_customer_idurl))
        return True
