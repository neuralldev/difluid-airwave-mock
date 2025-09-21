
from bleak import BleakScanner, BleakClient
import asyncio
import struct
import time
import types
from typing import List
from enum import StrEnum, IntEnum
from concurrent.futures import ProcessPoolExecutor


#Connected to AirWave 302291
#[Service]  000000e3-0000-1000-8000-00805f9b34fb (Handle: 40): Vendor specific
#  [Characteristic]  0000ff01-0000-1000-8000-00805f9b34fb (Handle: 41): Vendor specific  ( ['read', 'notify', 'write'] )  , Value: bytearray(b'\xff')
#    [Descriptor]  00002902-0000-1000-8000-00805f9b34fb (Handle: 43): Client Characteristic Configuration  Value:  bytearray(b'')
#  [Characteristic]  0000aa01-0000-1000-8000-00805f9b34fb (Handle: 44): Vendor specific  ( ['read', 'notify', 'write'] )  , Value: bytearray(b'\xff')
#    [Descriptor]  00002902-0000-1000-8000-00805f9b34fb (Handle: 46): Client Characteristic Configuration  Value:  bytearray(b'')

# test device
# BD   98:88:e0:a6:51:6e
# SN   F21E15806A05002
# FW   V003
# NAME AirWave 302291

AIRWAVE_PREFIX= "AirWave " # all devices start with this name

class AirwaveUUID(StrEnum):
    AIRWAVE_SERVICE_UUID = "000000e3-0000-1000-8000-00805f9b34fb" # service UUID to discover devices
    AIRWAVE_DIALOG_UUID  = "0000aa01-0000-1000-8000-00805f9b34fb" # clear text channel characteristic

class AirwaveFanMode(IntEnum):
    STANDARD=0
    EXTREME=1
    FAN=2
    
class AirwaveLanguages(IntEnum):
    CHINESE1=0
    CHINESE2=1
    ENGLISH=2
    JAPANESE=3
    KOREAN=4
    
class AirwaveFanLimits(IntEnum):
    MINIMUM=30
    MAXIMUM=100

class AirwaveFunctions(IntEnum):
    DEVICEINFO=0
    DEVICESETTING=1
    DEVICEACTIONS=3
    
class AirwaveSpeed(IntEnum):
    MINIMUM=30
    MAXIMUM=100
    
class AirwaveState(IntEnum):
    ON = 1
    OFF = 0

class DiFluidProtocol:
    """
    https://github.com/DiFluid/difluid-sdk-demo/blob/master/docs/difluid-protocol.md
    """
    PREAMBLE = b'\xdf\xdf'
    SUFFIX = b'\x0a\x0a'

        # les messages sont au format : 
        # préambule : 2 octets 0xDF 0xDF
        # Fonction : 1 octet
        # commande : 1 octet
        # longueur de la commande = n : 1 octet
        # données : n octets 
        # checksum : 1 octet
        # suffixe de clôture : 2 octets 0x0A 0x0A

    def build_full_message(self, function: int, command: int, data: bytes = b'') -> bytes:
        """
        [PREAMBLE][function][command][length][data][checksum]
        """
        length = len(data)
        payload = self.PREAMBLE + struct.pack('BBB', function, command, length) + data
        checksum = (sum(payload) & 0xFF)
        full_payload = payload + struct.pack('B', checksum)
        return full_payload

    def parse_full_message(self, payload: bytes) -> dict:
        """
        Décode  payload 
        [function][command][length][data][checksum]
        """
        if len(payload) < 6 or not payload.startswith(self.PREAMBLE) :
            return {'valid':False}
        function = payload[2]
        command = payload[3]
        length = payload[4]
        if len(payload) < 4 + length:
            return {'valid':False}
        data = payload[5:5+length]
        checksum = payload[5+length]
        expected_checksum = (sum(payload[:5+length]) & 0xFF)
        valid = checksum == expected_checksum
        if not valid:
            return {'valid':False}
        else:
            return {
                'function': function,
                'command': command,
                'length': length,
                'data': data,
                'checksum': checksum,
                'valid': valid
            }

    def __init__(self):
        self.buffer = bytearray()

class DiFluidDevice(DiFluidProtocol):
    def __init__(self):
        super().__init__()
        self.address = ''
        self.service_uuid = AirwaveUUID.AIRWAVE_SERVICE_UUID
        self.info_uuid = AirwaveUUID.AIRWAVE_DIALOG_UUID
        self.client = None
        self.name = None
        
    async def scan(self)->bool:
        print("Scanning for Bluetooth devices...")
        devices = await BleakScanner.discover(service_uuids=[self.service_uuid])
        for device in devices:
            if device.name is not None and device.name.startswith(AIRWAVE_PREFIX):
                print(f"Found device: {device.name} - {device.address}")
                self.address = device.address
                self.name = device.name
                print(f"Found target device {device.name} with address {device.address}")
                return True        
        return False
        
    async def connect(self)->bool:
        self.client = BleakClient(self.address)
        await self.client.__aenter__()
        return self.client.is_connected

    async def disconnect(self)->bool:
        if self.client:
            await self.client.__aexit__(None, None, None)
            self.client = None
        return False

    async def send_command(self, function: int, command: int, data: bytes = b'')->bool:
        if self.client is None:
            return False
        msg = self.build_full_message(function, command, data)
        status = False
        try:
            status = await self.client.write_gatt_char(char_specifier=self.info_uuid, data=msg, response=True)
        except Exception as e:
            print(f"Error sending : {e}")
        if status is None:
            status = False
        return status

    async def read_response(self):
        if self.client is None:
            return None
        try:
            value = await self.client.read_gatt_char(self.info_uuid)
            d:dict = self.parse_full_message(value)
            if d["valid"]:
                return d["data"]
        except Exception as e:
            print(f"Error reading : {e}")
            return None
     
    async def get_device_sn(self):
        await self.send_command(0x00, 0x00)
        status = await self.read_response()
        if status is None:
            return ''
        else:
            return status

    async def get_device_model(self):
        await self.send_command(0x00, 0x01)
        status = await self.read_response()
        if status is None:
            return -1
        else:
            return status

    async def get_firmware_version(self): 
        await self.send_command(0x00, 0x02)
        status = await self.read_response()
        if status is None:
            return ''
        else:
            return status

    async def get_language(self):
        await self.send_command(0x01, 0x06)
        status = await self.read_response()
        if status is None:
            return -1
        else:
            return status

    # 0,1 = chinese
    # 2 = english
    # 3 = Japanese
    # 4 = Korean
    async def Set_language(self, value: int):
        if value is None or value not in AirwaveLanguages:
            return None
        payload = struct.pack('BB', value, 0,0,0)
        await self.send_command(0x01, 0x06, payload)
        return await self.read_response()

    # 0 for extreme
    # 1 for standard
    # 2 for fan only
    async def get_mode(self):
        await self.send_command(0x03, 0x00)
        return await self.read_response()

    async def set_mode(self, value: int):
        if value is None or value not in AirwaveFanMode:
            return None
        payload = struct.pack('BB', value)
        await self.send_command(0x03, 0x00, payload)
        return await self.read_response()

    async def get_succionspeed(self):
        await self.send_command(0x03, 0x01)
        return await self.read_response()

    async def set_succionspeed(self, value: int):
        if value is None or value not in AirwaveSpeed:
            return False
        payload = struct.pack('BB', value)
        await self.send_command(0x03, 0x00, payload)
        return await self.read_response()

    async def get_state(self):
        await self.send_command(0x03, 0x02)
        return await self.read_response()

    async def set_state(self, value: int):
        if value is None or value not in AirwaveState:
            return False
        payload = struct.pack('BB', value)
        await self.send_command(0x03, 0x02, payload)
        return await self.read_response()

    # two floats in little endian format, first is inlet temperature and second is catalyst
    async def get_temps(self) -> dict:
        await self.send_command(0x03, 0x03)
        t = await self.read_response()
        if t is None:
            return {
                'inlet': -1.0,
                'catalyst': -1.0
            }
        # explode t in 8 bytes in two little endian floats : inlet, catalyst
        format_string = '<ff'
        try:
            inlet, catalyst = struct.unpack(format_string, t)
            print(f"Le premier float est : {inlet}")
            print(f"Le deuxième float est : {catalyst}")
        except struct.error as e:
            print(f"Erreur de décompression : {e}")
            return {
                'inlet': -1.0,
                'catalyst': -1.0
            }
        return {
            'inlet': inlet,
            'catalyst': catalyst
        }

async def main():

    print("starting")
    airwaveClient = DiFluidDevice()
    executor = ProcessPoolExecutor(2)
    loop = asyncio.new_event_loop()
    
    print ("scanning")
    status = await airwaveClient.scan()
    print ("scan finished")
    if status:
        status = await airwaveClient.connect()
        if status:
            print ("connected")
        else:
            print("not connected")
            return
    else:
        print ('no airwave found')
        return
                            
    #print('reading model')
    #model = await airwaveClient.get_device_model()
    print('reading sn')
    sn = await airwaveClient.get_device_sn()
    #print('reading version')
    #version = await airwaveClient.get_firmware_version()
    print(f"sn={sn}")
    print('read state')
    await airwaveClient.disconnect()
    print('disconnected')
    return
    state = loop.run_in_executor(executor,airwaveClient.get_state)
    if state==0:
        print("airwave is running")
    else:
        print('airwave is stopped')
    print("reading mode")
    mode = loop.run_in_executor(executor,airwaveClient.get_mode)
    if mode is None:
        print ("nothing")
    elif mode == 0:
        print ("Standard")
    elif mode == 1:
        print ("Extreme")
    elif mode == 2:
        print ("Fan only")

    print("reading speed")
    speed = loop.run_in_executor(executor,airwaveClient.get_succionspeed)
    if speed is None:
        print ("nothing")
    else:
        print(f"speed={speed}%")
    print("reading temepratures")
    t:dict={}
    t = loop.run_in_executor(executor,airwaveClient.get_temps)
    inlet = t["inlet"]
    catalyst = t["catalyst"]
    print(f"inlet={inlet}°C catalyst={catalyst}°C")
        
if __name__ == "__main__":

    asyncio.run(main())
