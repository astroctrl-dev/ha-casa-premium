# Swegon CASA protocol decoder.
# Decodes received protocol frames into structured
# ventilation status and sensor values.

def crc16(data):
    crc = 0xffff
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xffff
    return crc

class FrameParser:
    def __init__(self):
        self.buffer = bytearray()
        self.crc_errors = 0

    def feed(self, chunk):
        self.buffer.extend(chunk)
        while True:
            start = self.buffer.find(b'\xcc\x64')
            if start < 0:
                keep = 1 if self.buffer.endswith(b'\xcc') else 0
                del self.buffer[:len(self.buffer)-keep]
                return
            del self.buffer[:start]
            if len(self.buffer) < 6:
                return
            length = self.buffer[5]
            if not 1 <= length <= 30:
                del self.buffer[0]
                continue
            total = length + 8
            if len(self.buffer) < total:
                return
            frame = bytes(self.buffer[:total])
            if crc16(frame[1:-2]) != int.from_bytes(frame[-2:], 'big'):
                self.crc_errors += 1
                del self.buffer[0]
                continue
            del self.buffer[:total]
            yield frame

def signed(value):
    return value if value < 128 else value - 256

def decode(frame):
    """Decode received CASA protocol frames into structured values."""
    cmd = frame[6]
    d = frame[9:-2]
    if cmd == 0x21 and len(d) >= 4:
        return {'operating_mode': signed(d[0]), 'unit_state': signed(d[1]), 'fan_speed': d[3] & 0x0f}
    if cmd == 0x71 and len(d) >= 13:
        names = ('outdoor_temp','supply_temp','extract_temp','supply_temp_heated','t5','t6','t7','exhaust_temp','co2','humidity')
        out = {key: signed(d[i]) for i,key in enumerate(names)}
        out.update(supply_fan_rpm=d[10]*10, extract_fan_rpm=d[11]*10, efficiency=signed(d[12]))
        if out['extract_temp'] != out['outdoor_temp']:
            delta = out['extract_temp']-out['outdoor_temp']
            out['efficiency_supply_calc'] = int((out['supply_temp']-out['outdoor_temp'])/delta*100)
            out['efficiency_extract_calc'] = int((out['extract_temp']-out['exhaust_temp'])/delta*100)
        else:
            # Overwrite previous calculations when this sample is undefined.
            out['efficiency_supply_calc'] = None
            out['efficiency_extract_calc'] = None
        return out
    if cmd == 0x73 and len(d) >= 15:
        flags0 = ('heating','cooling','bypass','freeze_protection','preheat','chilling','preheater_overheat','reheat')
        flags1 = ('fireplace','underpressure_compensation','external_boost','humidity_boost','co2_boost','defrosting','defrost_starter','tf_stop')
        out = {name: bool(d[0] & (1 << i)) for i,name in enumerate(flags0)}
        out.update({name: bool(d[1] & (1 << i)) for i,name in enumerate(flags1)})
        flags3 = {'external_boost_function':2,'external_fireplace_function':3,'filter_guard_status':4,'ir_freeze_protection':5,'emergency_stop':7}
        flags7 = ('reheating_freezing_alarm','reheating_overheat_alarm','ir_sensor_failure','supply_fan_failure','extract_fan_failure','temperature_deviation_failure')
        flags8 = ('efficiency_alarm','filter_guard_alarm','service_reminder','temperature_failure')
        out.update({name: bool(d[3] & (1 << bit)) for name,bit in flags3.items()})
        out.update({name: bool(d[7] & (1 << i)) for i,name in enumerate(flags7)})
        out.update({name: bool(d[8] & (1 << i)) for i,name in enumerate(flags8)})
        out.update(afterheating_supply_setpoint=signed(d[10]),afterheating_room_setpoint=signed(d[11]),supply_fan_virtual_speed=signed(d[12]),extract_fan_virtual_speed=signed(d[13]),unit_status=signed(d[14]))
        return out
    # Read-only device identification (validated against captured 0x97/0x75).
    if cmd == 0x97 and len(d) >= 6:
        model = bytes(d[:6]).split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
        return {"model": model} if model else {}

    if cmd == 0x75 and len(d) >= 7:
        # Recorded: 01 01 33 00 0E 01 47 ... -> 1.51 and 1.71.
        # Do not decode 0x0E or remaining bytes as firmware without evidence.
        return {
            "firmware_rc": f"{d[1]}.{d[2]:02d}",
            "firmware_fst": f"{d[5]}.{d[6]:02d}",
        }

    return {}

# Verified against physical CASA panel captures, 2026-11-05.
MODE_CODES = {
    (0x01, 0x01, 0x00): 'Away',
    (0x04, 0x04, 0x01): 'Home',
}
BOOST_DURATIONS = {0: 'Boost permanent', 30: 'Boost 30',
                   60: 'Boost 60', 120: 'Boost 120'}


def decode_actual_mode(frame):
    """Return (select option, boost minutes) from an observed 0x73 frame.

    Fireplace is a temporary overlay. When its flag clears, the underlying
    Away/Home/Boost state is decoded again without an HA timer.
    """
    if (len(frame) < 26 or frame[2:5] != b'\x85\xfd\x0a'
            or frame[6] != 0x73):
        return None
    data = frame[9:-2]
    if len(data) < 15:
        return None
    if data[1] & 0x01:
        return 'Fireplace 10', None
    triplet = tuple(data[12:15])
    if triplet in MODE_CODES:
        return MODE_CODES[triplet], None
    if triplet == (0x05, 0x05, 0x02):
        duration = data[5]
        if duration in BOOST_DURATIONS:
            return BOOST_DURATIONS[duration], duration
    return None

