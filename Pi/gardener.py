#!/usr/bin/env python3
 
import logging
import struct
import array
import sys
from enum import Enum

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service

from ble import (
    Advertisement,
    Characteristic,
    Service,
    Application,
    find_gatt_manager,
    Descriptor,
    Agent,
)


BLUEZ_SERVICE_NAME = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
MANUFACTURER_DAVE = [0x64, 0x61, 0x76, 0x65]
AGENT_PATH = "/dave/agent"


class NotPermittedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotPermitted"


def register_application_callback():
    logger.info("GATT application registered")


def register_application_error_callback(error):
    logger.critical("Failed to register application: " + str(error))
    mainloop.quit()


class GardenerService(Service):
    """
    Dummy test service that provides characteristics and descriptors that
    exercise various API functionality.

    """

    GARDENER_SVC_UUID = "a0445a21-158f-4ca8-840d-6ec56ca58962"

    def __init__(self, bus, index):
        Service.__init__(self, bus, index, self.GARDENER_SVC_UUID, True)
        self.add_characteristic(WaterPlantsCharacteristic(bus, 0, self))


class WaterPlantsCharacteristic(Characteristic):
    uuid = "7e709c77-1844-46e7-8fd0-27b0b2382ee8"
    description = b"Get/set machine power state {'ON', 'OFF', 'UNKNOWN'}"

    class State(Enum):
        on = "ON"
        off = "OFF"
        unknown = "UNKNOWN"

        @classmethod
        def has_value(cls, value):
            return value in cls._value2member_map_

    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index, self.uuid, ["encrypt-read", "encrypt-write"], service,
        )

        self.value = [0xFF]
        self.add_descriptor(CharacteristicUserDescriptionDescriptor(bus, 1, self))

    def ReadValue(self, options):
        logger.debug("WaterPlantsCharacteristic read: " + repr(self.value))
        res = None
        try:
            self.value = bytearray(self.State.off, encoding="utf8")
        except Exception as e:
            logger.error(f"Error getting status {e}")
            self.value = bytearray(self.State.unknown, encoding="utf8")

        return self.value

    def WriteValue(self, value, options):
        logger.debug("WaterPlantsCharacteristic write: " + repr(value))
        cmd = bytes(value).decode("utf-8")

        # if self.State.has_value(cmd):
        #     # write it to machine
        #     logger.info("writing {cmd} to machine")
        #     data = {"cmd": cmd.lower()}
        #     try:
        #         res = requests.post(VivaldiBaseUrl + "/vivaldi/cmds", json=data)
        #     except Exceptions as e:
        #         logger.error(f"Error updating machine state: {e}")
        # else:
        #     logger.info(f"invalid state written {cmd}")
        #     raise NotPermittedException


        logger.debug("I'm gonna water the plants")

        self.value = value


class CharacteristicUserDescriptionDescriptor(Descriptor):
    """
    Writable CUD descriptor.
    """

    CUD_UUID = "2901"

    def __init__(
        self, bus, index, characteristic,
    ):

        self.value = array.array("B", characteristic.description)
        self.value = self.value.tolist()
        Descriptor.__init__(self, bus, index, self.CUD_UUID, ["read"], characteristic)

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        if not self.writable:
            raise NotPermittedException()
        self.value = value


class GardenerAdvertisement(Advertisement):
    def __init__(self, bus, index):
        Advertisement.__init__(self, bus, index, "peripheral")
        self.add_manufacturer_data(
            0xFFFF, MANUFACTURER_DAVE,
        )
        self.add_service_uuid(GardenerService.GARDENER_SVC_UUID)
        self.add_local_name("Gardener")
        self.include_tx_power = True


def register_advertisement_callback():
    logger.info("Advertisement registered")


def register_advertisement_error_callback(error):
    logger.critical("Failed to register advertisement: " + str(error))
    mainloop.quit()


MainLoop = None
try:
    from gi.repository import GLib

    MainLoop = GLib.MainLoop
except ImportError:
    import gobject as GObject

    MainLoop = GObject.MainLoop


#set up logging
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

logHandler = logging.StreamHandler()
logHandler.setFormatter(formatter)

filelogHandler = logging.FileHandler("gardener.log")
filelogHandler.setFormatter(formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(logHandler)
logger.addHandler(filelogHandler)


mainloop = None


def main():
    global mainloop

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    # get the system bus
    bus = dbus.SystemBus()
    # get the ble controller
    gatt_manager = find_gatt_manager(bus)

    if not gatt_manager:
        logger.critical("GattManager1 interface not found")
        return

    bluez_thing = bus.get_object(BLUEZ_SERVICE_NAME, gatt_manager)

    bluetooth_adapter_props = dbus.Interface(bluez_thing, "org.freedesktop.DBus.Properties")
    bluetooth_adapter_props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(1))

    obj = bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez")

    mainloop = MainLoop()

    agent = Agent(bus, AGENT_PATH)
    agent_manager = dbus.Interface(obj, "org.bluez.AgentManager1")
    agent_manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")

    logger.info("Registering advertisment...")
    advertisement = GardenerAdvertisement(bus, 0)
    advertising_manager = dbus.Interface(bluez_thing, LE_ADVERTISING_MANAGER_IFACE)
    advertising_manager.RegisterAdvertisement(
        advertisement.get_path(),
        {},
        reply_handler=register_advertisement_callback,
        error_handler=register_advertisement_error_callback,
    )

    logger.info("Registering GATT application...")
    application = Application(bus)
    application.add_service(GardenerService(bus, 2))
    gatt_manager = dbus.Interface(bluez_thing, GATT_MANAGER_IFACE)
    gatt_manager.RegisterApplication(
        application.get_path(),
        {},
        reply_handler=register_application_callback,
        error_handler=[register_application_error_callback],
    )
    
    agent_manager.RequestDefaultAgent(AGENT_PATH)

    mainloop.run()
    # ad_manager.UnregisterAdvertisement(advertisement)
    # dbus.service.Object.remove_from_connection(advertisement)


if __name__ == "__main__":
    main()
