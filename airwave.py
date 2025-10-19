# airwave.py
# Python module to interact with DiFluid AirWave devices over Bluetooth Low Energy (BLE).
# Implements scanning, connecting, sending commands, and receiving notifications.
# Uses the bleak library for BLE communication.
# (c) 2025 TiLau, general puublic open source license.
# Note: This code is provided as-is without warranty. Use at your own risk.

import asyncio
import struct
from bleak import BleakScanner, BleakClient
from enum import StrEnum, IntEnum

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
    PREAMBLE = b'\xdf\xdf'

    def build_full_message(self, function: int, command: int, data: bytes = b'') -> bytes:
        length = len(data)
        payload = self.PREAMBLE + struct.pack('BBB', function, command, length) + data
        checksum = (sum(payload) & 0xFF)
        full_payload = payload + struct.pack('B', checksum)
        return full_payload

    def parse_messages_by_delimiter(self, received_bytes: bytes, delimiter: bytes = PREAMBLE) -> list[bytes]:
        messages_raw = received_bytes.split(delimiter)
        messages = [delimiter + part for part in messages_raw[1:] if part]
        return messages
        
    def parse_full_message(self, payload: bytes) -> dict:
        if len(payload) < 6 or not payload.startswith(self.PREAMBLE) :
            return {'valid': False, 'error': 'Invalid preamble or length'}
        
        function = payload[2]
        command = payload[3]
        length = payload[4]
        
        if len(payload) < 5 + length + 1: # en-tête (3) + préambule (2) + données + checksum (1)
            return {'valid': False, 'error': 'Payload too short for declared length'}
        
        data = payload[5:5+length]
        checksum = payload[5+length]
        expected_checksum = (sum(payload[:5+length]) & 0xFF)
        
        valid = checksum == expected_checksum
        if not valid:
            return {'valid': False, 'error': 'Checksum mismatch'}
        else:
            return {
                'function': function,
                'command': command,
                'length': length,
                'data': data,
                'checksum': checksum,
                'valid': valid
            }

class DiFluidDevice(DiFluidProtocol):
    def __init__(self):
        super().__init__()
        self.address = ''
        self.service_uuid = AirwaveUUID.AIRWAVE_SERVICE_UUID
        self.info_uuid = AirwaveUUID.AIRWAVE_DIALOG_UUID
        self.client = None
        self.name = None
        self.responses = asyncio.Queue() # Utiliser une queue pour une gestion asynchrone des réponses
        self._notification_task = None
    
    # La méthode de scan n'a pas besoin de l'instance client, mais c'est bien de la laisser
    # dans la classe pour regrouper la logique.
    async def scan(self)->bool:
        print("Scanning for Bluetooth devices...")
        devices = await BleakScanner.discover(service_uuids=[self.service_uuid], timeout=10.0)
        for device in devices:
            if device.name is not None and device.name.startswith(AIRWAVE_PREFIX):
                print(f"Found device: {device.name} - {device.address}")
                self.address = device.address
                self.name = device.name
                return True        
        print('No AirWave device found.')
        return False
        
    async def connect(self):
        if not self.address:
            print("No device address to connect to.")
            return False
        try:
            self.client = BleakClient(self.address)
            await self.client.connect()
            await self.send_command(0x01,0x01,b"DIFLUIDMOCK") # send a name different than "OmniFlux" which disables auto/control mode (V500 firmware)
            print("Connected successfully.")
            return True
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    async def disconnect(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            print("Disconnected successfully.")
        self.client = None

    def notification_handler(self, sender, data):
        #print(f"Notification reçue de {sender}: {data.hex()}")
        try:
            # On utilise functools.partial pour s'assurer que self est bien capturé
            # car le handler s'exécute dans une boucle d'événements potentiellement différente
            # on exécute parse_messages_by_delimiter
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(self.process_notification_data, data)
        except Exception as e:
            print(f"Error in notification handler: {e}")
            
    def process_notification_data(self, data):
        # Cette fonction s'exécute dans la boucle d'événements principale
        messages = self.parse_messages_by_delimiter(data)
        for msg_bytes in messages:
            parsed_msg = self.parse_full_message(msg_bytes)
            if parsed_msg.get('valid'):
                self.responses.put_nowait(parsed_msg)

    async def send_command(self, function: int, command: int, data: bytes = b'')->bool:
        if not self.client or not self.client.is_connected:
            return False
        msg = self.build_full_message(function, command, data)
        try:
            await self.client.write_gatt_char(char_specifier=self.info_uuid, data=msg, response=True)
            return True
        except Exception as e:
            print(f"Error sending command: {e}")
            return False

    async def subscribe(self):
        if not self.client or not self.client.is_connected:
            return
        
        # On s'abonne une seule fois.
        await self.client.start_notify(self.info_uuid, self.notification_handler)
        print("Subscribed to notifications. Waiting for data...")

    async def get_response(self, function: int, command: int, timeout: float = 5.0):
        # Vide la queue avant d'envoyer la commande pour éviter de récupérer une ancienne réponse
        while not self.responses.empty():
            self.responses.get_nowait()
            
        await self.send_command(function, command)
        
        start_time = asyncio.get_running_loop().time()
        while True:
            try:
                # Attend une réponse dans la queue avec un timeout
                response = await asyncio.wait_for(self.responses.get(), timeout=timeout)
                if response['function'] == function and response['command'] == command:
                    return response
            except asyncio.TimeoutError:
                print(f"Timeout: no answer to command {function}-{command}.")
                return None
            
            # S'il y a des réponses non pertinentes, on continue à attendre
            if asyncio.get_running_loop().time() - start_time > timeout:
                return None

    async def get_device_sn(self):
        response = await self.get_response(0x00, 0x00)
        return str(response['data'], 'utf-8') if response else None
    
    async def get_device_model(self):
        response = await self.get_response(0x00, 0x01)
        return str(response['data'], 'utf-8') if response else None

    async def get_firmware_version(self): 
        response = await self.get_response(0x00, 0x02)
        return str(response['data'], 'utf-8') if response else None

    async def get_state(self):
        response = await self.get_response(0x03, 0x02)
        if response and response['data']:
            return int.from_bytes(response['data'], 'big')
        return -1
    
    async def get_mode(self):
        response = await self.get_response(0x03, 0x00)
        if response and response['data']:
            return int.from_bytes(response['data'], 'big')
        return -1

    async def get_succionspeed(self):
        response = await self.get_response(0x03, 0x01)
        if response and response['data']:
            return int.from_bytes(response['data'], 'big')
        return -1

    async def set_state(self, value: int):
        if value is None or value not in AirwaveState:
            return False
        payload = struct.pack('B', value)
        return await self.send_command(0x03, 0x02, payload)

    async def set_mode(self, value: int):
        if value is None or value not in AirwaveFanMode:
            return False
        payload = struct.pack('B', value)
        return await self.send_command(0x03, 0x00, payload)

    async def set_succionspeed(self, value: int):
        if value is None or value < AirwaveSpeed.MINIMUM or value > AirwaveSpeed.MAXIMUM:
            return False
        payload = struct.pack('B', value)
        return await self.send_command(0x03, 0x01, payload)

    async def get_temps(self) -> dict:
        response = await self.get_response(0x03, 0x03)
        if response and response['data']:
            try:
                inlet, catalyst = struct.unpack('<ff', response['data'])
                return {
                    'inlet': round(inlet,1),
                    'catalyst': round(catalyst,1)
                }
            except struct.error as e:
                print(f"Error {e}")
        return {
            'inlet': -1.0,
            'catalyst': -1.0
        }
    
async def main_async_flow():
    airwaveClient = DiFluidDevice()
    
    if not await airwaveClient.scan():
        print('no airwave found')
        return
    
    if not await airwaveClient.connect():
        print('not connected')
        return

    # On s'abonne aux notifications une seule fois au début
    await airwaveClient.subscribe()

    print('reading model')
    model = await airwaveClient.get_device_model()
    print(f"model={model}")
    
    print('reading sn')
    sn = await airwaveClient.get_device_sn()
    print(f"sn={sn}")
    
    print('reading version')
    version = await airwaveClient.get_firmware_version()
    print(f"firmware={version}")

    print("reading state")
    state = await airwaveClient.get_state()
    if state == AirwaveState.ON:
        print("airwave is running")
    elif state == AirwaveState.OFF:
        print("airwave is stopped")
    else:
        print('cannot read state')

    print("reading mode")
    mode = await airwaveClient.get_mode()
    if mode == AirwaveFanMode.STANDARD:
        print ("Standard")
    elif mode == AirwaveFanMode.EXTREME:
        print ("Extreme")
    elif mode == AirwaveFanMode.FAN:
        print ("Fan only")
    else:
        print ("nothing")

    print("reading speed")
    speed = await airwaveClient.get_succionspeed()
    if speed is not None and speed != -1:
        print(f"speed={speed}%")
    else:
        print("cannot read speed")

    print("reading temperatures")
    temps = await airwaveClient.get_temps()
    print(f"inlet={temps['inlet']}°C catalyst={temps['catalyst']}°C")

    print("setting mode")
    await airwaveClient.set_mode(AirwaveFanMode.FAN)
    print("setting state")
    await airwaveClient.set_state(AirwaveState.ON)
    print("setting speed")
    await airwaveClient.set_succionspeed(35)

    # Déconnexion en fin de script
    await airwaveClient.disconnect()
    print('disconnected')
        
if __name__ == "__main__":
    asyncio.run(main_async_flow())
    