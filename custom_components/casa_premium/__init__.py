"""Swegon CASA Premium TCP integration with protocol logging and mode control."""
import socket
from collections import deque
from datetime import timezone
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import voluptuous as vol
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, discovery
from .decoder import FrameParser, decode, decode_actual_mode, crc16
from .protocol_logger import ProtocolLogger
from .quality import QualityMonitor
from homeassistant.components import websocket_api
from homeassistant.helpers.storage import Store

DOMAIN = 'casa_premium'
LOGGING_ENTITY = 'input_boolean.casa_ventilasjon_logging'
READ_ONLY_PLATFORMS = ('sensor', 'binary_sensor')
READ_ONLY_MESSAGE = 'CASA Premium is read-only; commands to the ventilation unit are disabled'
MODE_CONFIRM_TIMEOUT_SECONDS = 10
RECEIVE_TIMEOUT_SECONDS = 60
RECONNECT_DELAY_SECONDS = 5
CLOCK_SYNC_HOUR = 4
CLOCK_SYNC_MINUTE = 15
CLOCK_DRIFT_THRESHOLD_SECONDS = 60
CLOCK_RESET_DRIFT_THRESHOLD_SECONDS = 120
CLOCK_RESET_RETRY_SECONDS = 300
# Suppress automatic clock writes during local HA day rollover.
CLOCK_MIDNIGHT_GUARD_MINUTES = 5
CLOCK_STATUS_TIMEOUT_SECONDS = 90
CLOCK_VERIFY_TOLERANCE_SECONDS = 5
COOLING_CONFIRM_TIMEOUT_SECONDS = 12
TEMPERATURE_SETTING_CONFIRM_TIMEOUT_SECONDS = 60
_LOGGER = logging.getLogger(__name__)
MODE_PAYLOADS = {
    'Away': bytes.fromhex('00 00 00 04 02 00 00 00'),
    'Home': bytes.fromhex('01 00 00 04 02 00 00 00'),
    'Boost 30': bytes.fromhex('02 00 00 04 02 00 00 1E'),
    'Boost 60': bytes.fromhex('02 00 00 04 02 00 00 3C'),
    'Boost 120': bytes.fromhex('02 00 00 04 02 00 00 78'),
    'Boost permanent': bytes.fromhex('02 00 00 04 02 00 00 00'),
}


def make_mode_frame(option):
    """Build the panel's 0x20 command for a normal operating mode."""
    frame = bytes.fromhex('CC 64 45 0A 01 0B 20 00 81') + MODE_PAYLOADS[option]
    return frame + crc16(frame[1:]).to_bytes(2, 'big')


def make_fireplace_frame(enabled):
    """Captured panel 0x30 command: 02=on, 01=off."""
    value = '02' if enabled else '01'
    frame = bytes.fromhex('CC 64 45 0A 01 08 30 00 10 00 00 00 00 ' + value)
    return frame + crc16(frame[1:]).to_bytes(2, 'big')


def make_clock_frame(now):
    """Reproduce captured panel's 0x54 time-set telegram (weekday, HH, MM, SS)."""
    if not (0 <= now.weekday() <= 6):
        raise ValueError('Invalid weekday')
    # The physical CASA panel changes weekday using selector 0x01.
    # 2026-11-07 traffic: 0x54/0x01 weekday=1->2, ACK and 0x55 readback=2.
    # 0x0E changes time but did NOT correct weekday (readback remained 1).
    prefix = bytes.fromhex('CC 64 45 0A 01 07 54 00 01')
    payload = bytes((now.weekday(), now.hour, now.minute, now.second))
    frame = prefix + payload
    return frame + crc16(frame[1:]).to_bytes(2, 'big')


# Panel labels correlated with 0x3C captured sequence 00...04.
# All five fan values verified against panel writes and 0x3D readback (2026-11-06).
COOLING_FAN_OPTIONS = {'No Change': 0, 'Away': 1, 'Home': 2,
                       'Boost': 3, 'Cooling': 4}
COOLING_FAN_LABELS = {value: name for name, value in COOLING_FAN_OPTIONS.items()}


def make_cooling_frame(payload, selector):
    """Panel 0x3C write, full 7-byte snapshot from 0x3D; change just one field."""
    if len(payload) != 7:
        raise ValueError('CASA cooling payload must contain 7 bytes')
    if selector not in (0x02, 0x10):
        raise ValueError('Unsupported CASA cooling parameter selector')
    frame = bytes.fromhex('CC 64 45 0A 01 0A 3C 01') + bytes((selector,)) + bytes(payload)
    return frame + crc16(frame[1:]).to_bytes(2, 'big')


def make_temperature_setting_frame(payload):
    """Captured 0x4C temperature ON/OFF write (selector 0x20, 11-byte snapshot)."""
    if len(payload) != 11 or payload[4] != 0x02 or payload[6] not in (0x00, 0xFF):
        raise ValueError('Invalid CASA temperature setting payload')
    prefix = bytes.fromhex('CC 64 45 0A 01 0E 4C 01 20')
    frame = prefix + bytes(payload)
    return frame + crc16(frame[1:]).to_bytes(2, 'big')


def make_supply_air_setpoint_frame(payload):
    """Panel-confirmed 0x4C command, selector 0x01, full 11-byte 0x4D snapshot."""
    if len(payload) != 11 or payload[4] != 0x01 or payload[1] not in range(130, 201):
        raise ValueError('Invalid CASA supply air setpoint payload')
    # Captured panel write: CC 64 45 0A 01 0E 4C 00 01 <11 bytes> CRC16
    prefix = bytes.fromhex('CC 64 45 0A 01 0E 4C 00 01')
    frame = prefix + bytes(payload)
    return frame + crc16(frame[1:]).to_bytes(2, 'big')


# Service-menu commands captured from the original CASA Premium panel.
# TX: cmd 0x22/0x24/0xA2/0x2A/0x2E/0x36; unit readback: next odd cmd.
SERVICE_CONFIG = {
    'supply_fan': (0x22, 0x23, 5, 0x01),
    'extract_fan': (0x24, 0x25, 5, 0x01),
    'fan_profiles': (0xA2, 0xA3, 6, 0x01),
    'co2_control': (0x2A, 0x2B, 4, 0x08),
    'external_control': (0x2E, 0x2F, 2, 0x01),
    'weekly_schedule': (0x36, 0x37, 8, 0x08),
    # Service -> Functions, captured directly from panel 2026-11-06.
    'service_reminder': (0x86, 0x87, 8, 0x02),
    'service_interval': (0x50, 0x51, 8, 0x01),
    'summer_night_cooling': (0x3C, 0x3D, 7, 0x01),
    'heating': (0x44, 0x45, 17, 0x01),
    'filter_monitor': (0x36, 0x37, 8, 0x01),
    'fireplace_function': (0x30, 0x31, 5, 0x08),
    'boost_special': (0x32, 0x33, 8, 0x02),
    'sa_limit': (0xA4, 0xA5, 4, 0x01),
    # Electric Air Heater: enabled field from 0x34/0x35 byte 5 (1-based).
    'electric_air_heater': (0x34, 0x35, 8, 0x10),
    # Shared 0x36/0x37 status with Filter Monitor and Weekly Schedule.
    'electric_air_heater_temperature': (0x36, 0x37, 8, 0x10),
}
SERVICE_FAN_PROFILES = ('Away', 'Home', 'Boost', 'Heating', 'Cooling', 'Chilling')
SERVICE_VERIFY_TIMEOUT_SECONDS = 70
SERVICE_FRESH_TIMEOUT_SECONDS = 60

# Week schedule slot write/read (all four observed and ACKed on original panel).
WEEK_SLOT_WRITES = (0x60, 0x62, 0x64, 0x66)
WEEK_SLOT_READS = (0x61, 0x63, 0x65, 0x67)
WEEK_MODE_LABELS = {'Away': 0, 'Home': 1, 'Boost': 2}
WEEK_MODE_VALUES = {v: k for k, v in WEEK_MODE_LABELS.items()}
WEEK_CONFIRM_SECONDS = 70  # Native panel round-trip readback approximately 26 s.


def make_week_slot_frame(slot, payload):
    if slot not in range(4) or len(payload) != 7:
        raise ValueError('Invalid weekly program slot/payload')
    prefix = bytes((0xCC, 0x64, 0x45, 0x0A, 0x01, 0x0A,
                    WEEK_SLOT_WRITES[slot], 0x01, 0xFF))
    frame = prefix + bytes(payload)
    return frame + crc16(frame[1:]).to_bytes(2, 'big')


def make_week_enable_frame(enabled):
    prefix = bytes.fromhex('CC 64 45 0A 01 04 6E 00 01')
    frame = prefix + bytes((0xFF if enabled else 0x00,))
    return frame + crc16(frame[1:]).to_bytes(2, 'big')


def make_service_frame(key, payload, selector=None):
    """Exact panel TX header and CRC16; never modify unrelated readback fields."""
    cmd, _read, size, default_selector = SERVICE_CONFIG[key]
    selector = default_selector if selector is None else selector
    if len(payload) != size:
        raise ValueError(f'{key}: expected {size} data bytes')
    # Confirmed from panel: weekly main-menu visibility (0x36, selector 0x08)
    # writes a single value (0x01 hidden / 0x02 visible), while 0x37
    # provides an eight-byte status snapshot. Never write all 8 bytes.
    # External control also writes a single byte.
    if key == 'weekly_schedule':
        tx_payload = bytes((payload[3],))
    elif key == 'external_control':
        tx_payload = bytes(payload[:1])
    else:
        tx_payload = bytes(payload)
    prefix = bytes((0xCC, 0x64, 0x45, 0x0A, 0x01, len(tx_payload) + 3,
                    cmd, 0x01, selector))
    frame = prefix + tx_payload
    return frame + crc16(frame[1:]).to_bytes(2, 'big')


def in_midnight_guard(local_time):
    """Protect 23:55-00:05 local day change from false weekday mismatch."""
    minutes = local_time.hour * 60 + local_time.minute
    return minutes >= (24 * 60 - CLOCK_MIDNIGHT_GUARD_MINUTES) or minutes < CLOCK_MIDNIGHT_GUARD_MINUTES


def clock_drift_seconds(clock_data, observed_at):
    """Compare CASA weekday+time to local HA time at the same instant."""
    weekday, hour, minute, second = clock_data
    if not (0 <= weekday <= 6 and 0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        return None
    casa_seconds = hour * 3600 + minute * 60 + second
    ha_seconds = observed_at.hour * 3600 + observed_at.minute * 60 + observed_at.second
    diff = casa_seconds - ha_seconds
    # Handle near-midnight rollover without a false 24-hour drift.
    diff = (diff + 43200) % 86400 - 43200
    return diff


CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({vol.Required(CONF_HOST): cv.string, vol.Optional(CONF_PORT, default=8899): cv.port})}, extra=vol.ALLOW_EXTRA)


class CasaReadOnlyError(HomeAssistantError):
    """An attempted device command was blocked before transmission."""


class CasaHub:
    @staticmethod
    def _require_writable():
        """This release has no opt-in write mode."""
        raise CasaReadOnlyError(READ_ONLY_MESSAGE)

    def _write_frame(self, frame):
        """Single command boundary: never forward bytes in the read-only release."""
        self._require_writable()

    def __init__(self, hass, host, port):
        self.hass, self.host, self.port = hass, host, port
        self.values = {}
        self.connected = False
        self.writer = None
        self.send_lock = asyncio.Lock()
        self.selected_mode = None
        self.actual_mode = None
        self.fireplace_active = None
        self.actual_boost_minutes = None
        self.mode_sync_status = 'unavailable'
        self.pending_mode = None
        self._mode_candidate = None
        self._mode_candidate_count = 0
        self._pending_ack = False
        self._pending_fireplace = None
        self._pending_matching_frames = 0
        self._pending_generation = 0
        self._pending_timeout_task = None
        self.listeners = set()
        self.task = None
        self.parser = FrameParser()
        self.quality = QualityMonitor()
        self.diagnostic_events = deque(maxlen=12000)
        self.diagnostic_seq = 0
        self.diagnostic_bytes = 0
        self.diagnostic_frames = 0
        self.diagnostic_crc_errors = 0
        self.diagnostic_decoded = 0
        self.protocol_logger = ProtocolLogger(hass.config.config_dir)
        self._logging_was_on = False
        self._logged_frames = 0
        self._logging_fault = False
        self.clock_data = None
        self.clock_observed_at = None
        self._clock_status_event = asyncio.Event()
        self._clock_ack_event = asyncio.Event()
        self._clock_sync_lock = asyncio.Lock()
        self._clock_ack_received = False
        self._clock_reset_last_attempt = None
        # Legacy state retained for parsing compatibility; it never grants write access.
        self.auto_clock_sync_enabled = False
        self._tz = ZoneInfo(hass.config.time_zone)
        self.cooling_settings = None
        self._cooling_last_seen = None
        self._cooling_status_event = asyncio.Event()
        self._cooling_lock = asyncio.Lock()
        self.temperature_setting_data = None  # 0x4D index=1, Temperature ON/OFF
        self.supply_air_setpoint_data = None  # 0x4D index=0, Supply Air Setpoint
        self._supply_air_setpoint_event = asyncio.Event()
        self._temperature_setting_event = asyncio.Event()
        self._temperature_setting_lock = asyncio.Lock()
        self.week_slots = [None] * 4
        self._week_slot_events = [asyncio.Event() for _ in range(4)]
        self._week_slot_locks = [asyncio.Lock() for _ in range(4)]
        self.week_enabled = None
        self._week_enabled_event = asyncio.Event()
        self._week_enabled_lock = asyncio.Lock()
        self.service_settings = {key: None for key in SERVICE_CONFIG}
        self._service_events = {key: asyncio.Event() for key in SERVICE_CONFIG}
        self._service_locks = {key: asyncio.Lock() for key in SERVICE_CONFIG}
        # Both labels mutate the same underlying 0x36/0x37 status payload.
        self._service_locks['filter_monitor'] = self._service_locks['weekly_schedule']
        self._service_locks['electric_air_heater_temperature'] = self._service_locks['weekly_schedule']
        self._service_locks['summer_night_cooling'] = self._cooling_lock


    @callback
    def subscribe(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    @callback
    def notify(self):
        for listener in tuple(self.listeners):
            listener()

    def logging_enabled(self):
        state = self.hass.states.get(LOGGING_ENTITY)
        return state is not None and state.state == 'on'

    def _record_frames(self, frames):
        self.protocol_logger.load()
        for frame in frames:
            self.protocol_logger.record(frame)
            self._logged_frames += 1
        if self._logged_frames >= 100:
            self.protocol_logger.flush()
            self._logged_frames = 0

    async def _process_logging(self, frames):
        enabled = self.logging_enabled()
        if enabled:
            if not self._logging_was_on:
                _LOGGER.info('CASA protocol logging ON; files in %s', self.hass.config.config_dir)
                self._logging_was_on = True
            if frames:
                try:
                    await self.hass.async_add_executor_job(self._record_frames, frames)
                    self._logging_fault = False
                except Exception:
                    if not self._logging_fault:
                        _LOGGER.exception('CASA protocol logging failed (sensor decoding continues)')
                    self._logging_fault = True
        elif self._logging_was_on:
            self._logging_was_on = False
            _LOGGER.info('CASA protocol logging OFF')
            try:
                await self.hass.async_add_executor_job(self.protocol_logger.flush)
            except Exception:
                _LOGGER.exception('CASA protocol logger flush failed')

    def _clear_pending(self):
        """Cancel current transaction without transmitting anything."""
        self._pending_generation += 1
        task = self._pending_timeout_task
        self._pending_timeout_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        self.pending_mode = None
        self._pending_fireplace = None
        self._pending_ack = False
        self._pending_matching_frames = 0

    def _reset_mode_readback(self):
        self._clear_pending()
        self.actual_mode = None
        self.fireplace_active = None
        self.actual_boost_minutes = None
        self.selected_mode = None
        self._mode_candidate = None
        self._mode_candidate_count = 0
        self.mode_sync_status = 'unavailable'

    async def _mode_timeout(self, generation):
        try:
            await asyncio.sleep(MODE_CONFIRM_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            return
        if generation != self._pending_generation or (self.pending_mode is None and self._pending_fireplace is None):
            return
        requested = self.pending_mode if self.pending_mode is not None else f'Fireplace={self._pending_fireplace}'
        _LOGGER.warning(
            'CASA mode %s not verified within %ss; actual readback: %s; ack: %s',
            requested, MODE_CONFIRM_TIMEOUT_SECONDS, self.actual_mode, self._pending_ack)
        self._clear_pending()
        self.selected_mode = self.actual_mode
        self.mode_sync_status = 'not_confirmed'
        self.notify()

    def _process_mode_response(self, frame):
        """Log ACK, but actual 0x73 status is authoritative."""
        if frame[2:5] != b'\x85\x01\x0a':
            return
        data = frame[9:-2]
        if self._pending_fireplace is not None and frame[6] == 0x30:
            if data and data[0] == 1:
                self._pending_ack = True
                _LOGGER.debug('CASA Fireplace ACK received')
        elif self.pending_mode is not None and frame[6] == 0x20:
            response = {
                'Away': (0, 1), 'Home': (1, 4),
                'Boost 30': (2, 5), 'Boost 60': (2, 5),
                'Boost 120': (2, 5), 'Boost permanent': (2, 5),
            }.get(self.pending_mode)
            if len(data) >= 3 and data[0] == 1 and tuple(data[1:3]) == response:
                self._pending_ack = True
                _LOGGER.debug('CASA mode %s ACK received', self.pending_mode)

    def _process_mode_status(self, frame):
        """Report only CASA-confirmed status, including Fireplace overlay."""
        if frame[2:5] != b'\x85\xfd\x0a' or frame[6] != 0x73:
            return
        data = frame[9:-2]
        if len(data) < 15:
            return

        fireplace = bool(data[1] & 0x01)
        decoded = decode_actual_mode(frame)
        mode, duration = decoded if decoded is not None else (None, None)
        candidate = (fireplace, mode, duration)
        if self._mode_candidate == candidate:
            self._mode_candidate_count += 1
        else:
            self._mode_candidate = candidate
            self._mode_candidate_count = 1

        if self._mode_candidate_count < 2:
            return

        changed = False
        if self.fireplace_active != fireplace:
            self.fireplace_active = fireplace
            changed = True
        if self.actual_mode != mode or self.actual_boost_minutes != duration:
            self.actual_mode = mode
            self.actual_boost_minutes = duration
            changed = True
        # Select must always reflect readback, not the last HA command.
        if self.selected_mode != mode:
            self.selected_mode = mode
            changed = True

        if self._pending_fireplace is not None:
            if fireplace == self._pending_fireplace:
                _LOGGER.info('CASA Fireplace %s confirmed by 0x73', 'ON' if fireplace else 'OFF')
                self._clear_pending()
                self.mode_sync_status = 'synced'
                changed = True
        elif self.pending_mode is not None:
            if mode == self.pending_mode:
                _LOGGER.info('CASA mode %s confirmed by 0x73', mode)
                self._clear_pending()
                self.mode_sync_status = 'synced'
                changed = True
        elif self.mode_sync_status == 'unavailable':
            self.mode_sync_status = 'synced'
            changed = True

        if changed:
            self.notify()

    def _process_clock_frame(self, frame):
        """Collect unsolicited time status and ACK, separate from mode readback."""
        if frame[6] == 0x55 and frame[2:5] == b'\x85\xfd\x0a':
            data = frame[9:-2]
            if len(data) >= 4 and all((
                0 <= data[0] <= 6,
                data[1] < 24, data[2] < 60, data[3] < 60,
            )):
                self.clock_data = tuple(data[:4])
                self.clock_observed_at = datetime.now(self._tz)
                self._clock_status_event.set()
                self.notify()
                # Clock reports are observational only in this release.
                # Even a legacy restored auto-sync flag must not schedule writes.
        elif (frame[6] == 0x54 and frame[2:5] == b'\x85\x01\x0a'
              and frame[8] == 0x01):
            data = frame[9:-2]
            if data and data[0] == 1:
                self._clock_ack_received = True
                self._clock_ack_event.set()

    async def sync_clock(self, *, force=False, automatic=False, use_recent_status=False):
        """Reject manual clock writes; automatic legacy calls are inert."""
        if automatic:
            return
        self._require_writable()
        if automatic and not self.auto_clock_sync_enabled:
            return
        async with self._clock_sync_lock:
            if automatic and not self.auto_clock_sync_enabled:
                return
            if not self.connected or self.writer is None or self.writer.is_closing():
                _LOGGER.warning('CASA clock sync skipped: disconnected')
                return

            # Manual button uses a recent, already received 0x55 status to
            # avoid waiting for another complete panel polling cycle.
            observed = self.clock_observed_at
            age = ((datetime.now(self._tz) - observed).total_seconds()
                   if observed is not None else None)
            cached_status_ok = (use_recent_status and self.clock_data is not None
                                and age is not None and 0 <= age <= 60)
            if cached_status_ok:
                _LOGGER.warning('CASA manual clock: using 0x55 status age %.1fs', age)
            else:
                _LOGGER.warning('CASA clock: awaiting next 0x55 status (timeout %ds)',
                                CLOCK_STATUS_TIMEOUT_SECONDS)
                self._clock_status_event.clear()
                try:
                    await asyncio.wait_for(
                        self._clock_status_event.wait(), CLOCK_STATUS_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    _LOGGER.warning('CASA clock sync skipped: no fresh 0x55 status')
                    return
            observed_at = self.clock_observed_at
            clock_data = self.clock_data
            if observed_at is None or clock_data is None:
                _LOGGER.warning('CASA clock sync skipped: incomplete status')
                return
            weekday_mismatch = clock_data[0] != observed_at.weekday()
            drift = clock_drift_seconds(clock_data, observed_at)
            if drift is None:
                _LOGGER.warning('CASA clock sync skipped: invalid status %s', clock_data)
                return
            # Clock readings may briefly cross midnight on different cycles.
            # Defer automatic sync until local HA has safely finished rollover.
            if not force and in_midnight_guard(observed_at):
                _LOGGER.debug('CASA automatic clock sync deferred during local midnight guard')
                return
            if not force and not weekday_mismatch and abs(drift) <= CLOCK_DRIFT_THRESHOLD_SECONDS:
                _LOGGER.info('CASA clock OK: drift %+ds; no write', drift)
                return

            _LOGGER.warning('CASA clock correcting: drift %+ds, weekday mismatch=%s',
                         drift, weekday_mismatch)
            if automatic and not self.auto_clock_sync_enabled:
                return
            self._clock_status_event.clear()
            self._clock_ack_event.clear()
            self._clock_ack_received = False
            try:
                async with self.send_lock:
                    if not self.connected or self.writer is None or self.writer.is_closing():
                        _LOGGER.warning('CASA clock sync aborted: disconnected')
                        return
                    if automatic and not self.auto_clock_sync_enabled:
                        _LOGGER.info('CASA auto clock sync cancelled: switch OFF')
                        return
                    now = datetime.now(self._tz)
                    if not force and in_midnight_guard(now):
                        _LOGGER.debug('CASA clock write deferred: local midnight guard')
                        return
                    outgoing_frame = make_clock_frame(now)
                    _LOGGER.warning('CASA clock TX 0x54 selector=0x01 data=%s',
                                    outgoing_frame[9:13].hex(' '))
                    self._write_frame(outgoing_frame)
                    await asyncio.wait_for(self.writer.drain(), timeout=5)
            except (OSError, asyncio.TimeoutError) as err:
                _LOGGER.warning('CASA clock write failed: %s', err)
                return
            try:
                await asyncio.wait_for(self._clock_ack_event.wait(), timeout=10)
                _LOGGER.warning('CASA clock 0x54 ACK received')
            except asyncio.TimeoutError:
                _LOGGER.warning('CASA clock write unconfirmed: no 0x54 ACK')
                return

            try:
                await asyncio.wait_for(
                    self._clock_status_event.wait(), CLOCK_STATUS_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                _LOGGER.warning('CASA clock write ACKed, but no 0x55 readback')
                return
            readback = self.clock_data
            read_at = self.clock_observed_at
            if readback is None or read_at is None:
                _LOGGER.warning('CASA clock readback missing')
                return
            result_drift = clock_drift_seconds(readback, read_at)
            if (readback[0] == read_at.weekday() and result_drift is not None
                    and abs(result_drift) <= CLOCK_VERIFY_TOLERANCE_SECONDS):
                _LOGGER.info('CASA clock sync confirmed: drift %+ds', result_drift)
            else:
                _LOGGER.warning(
                    'CASA clock readback mismatch: CASA day=%s, HA day=%s, drift=%s s; '
                    'weekday write may not have been accepted',
                    readback[0], read_at.weekday(), result_drift)

    def _process_temperature_setting_frame(self, frame):
        """Keep 0x4D index=0 (setpoint) and index=1 (ON/OFF) isolated."""
        if frame[6] != 0x4D or frame[2:5] != b'\x85\xfd\x0a':
            return
        data = frame[9:-2]
        if len(data) != 11 or data[6] not in (0x00, 0xFF):
            return
        if frame[7] == 0x00 and data[4] == 0x01:
            self.supply_air_setpoint_data = bytes(data)
            self._supply_air_setpoint_event.set()
            self.notify()
        elif frame[7] == 0x01 and data[4] == 0x02:
            self.temperature_setting_data = bytes(data)
            self._temperature_setting_event.set()
            self.notify()

    @property
    def temperature_setting_enabled(self):
        if self.temperature_setting_data is None:
            return None
        return self.temperature_setting_data[6] == 0xFF

    @property
    def supply_air_temperature_setpoint(self):
        """Panel setpoint from 0x4D index=0, tenths of degrees."""
        if self.supply_air_setpoint_data is None:
            return None
        return self.supply_air_setpoint_data[1] / 10.0

    async def set_supply_air_temperature_setpoint(self, temperature):
        """Write panel temperature with fresh 0x4D snapshot, verify via readback."""
        self._require_writable()
        if not 13 <= temperature <= 20 or float(temperature).is_integer() is False:
            raise ValueError('Supply air setpoint must be whole degrees from 13 to 20')
        target_raw = int(temperature) * 10
        # Serialize all 0x4C writes; use only index=0 readback for this field.
        async with self._temperature_setting_lock:
            if not self.connected or self.writer is None or self.writer.is_closing():
                raise ConnectionError('CASA TCP gateway is disconnected')
            self._supply_air_setpoint_event.clear()
            try:
                await asyncio.wait_for(self._supply_air_setpoint_event.wait(), timeout=60)
            except asyncio.TimeoutError as exc:
                raise TimeoutError('CASA fresh 0x4D temperature status not received') from exc
            if not self.connected or self.supply_air_setpoint_data is None:
                raise ConnectionError('CASA disconnected while awaiting 0x4D')
            payload = bytearray(self.supply_air_setpoint_data)
            if payload[1] == target_raw:
                return
            payload[1] = target_raw
            self._supply_air_setpoint_event.clear()
            async with self.send_lock:
                if not self.connected or self.writer is None or self.writer.is_closing():
                    raise ConnectionError('CASA disconnected before temperature setpoint write')
                self._write_frame(make_supply_air_setpoint_frame(payload))
                await asyncio.wait_for(self.writer.drain(), timeout=5)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + TEMPERATURE_SETTING_CONFIRM_TIMEOUT_SECONDS
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError('CASA supply air setpoint not confirmed via 0x4D')
                try:
                    await asyncio.wait_for(self._supply_air_setpoint_event.wait(), timeout=remaining)
                except asyncio.TimeoutError as exc:
                    raise TimeoutError('CASA supply air setpoint readback timed out') from exc
                if not self.connected or self.supply_air_setpoint_data is None:
                    raise ConnectionError('CASA disconnected during setpoint confirmation')
                if self.supply_air_setpoint_data[1] == target_raw:
                    _LOGGER.info('CASA supply air setpoint %s C confirmed via 0x4D', temperature)
                    return
                self._supply_air_setpoint_event.clear()

    async def set_temperature_setting(self, enabled):
        """Read-modify-write via 0x4C and confirm using actual 0x4D status."""
        self._require_writable()
        async with self._temperature_setting_lock:
            if not self.connected or self.writer is None or self.writer.is_closing():
                raise ConnectionError('CASA TCP gateway is disconnected')
            # Never write an old 0x4D snapshot: wait for the next full status.
            self._temperature_setting_event.clear()
            try:
                await asyncio.wait_for(self._temperature_setting_event.wait(), timeout=60)
            except asyncio.TimeoutError as exc:
                raise TimeoutError('CASA 0x4D fresh status not received') from exc
            if not self.connected or self.temperature_setting_data is None:
                raise ConnectionError('CASA disconnected while awaiting 0x4D')
            payload = bytearray(self.temperature_setting_data)
            target = 0xFF if enabled else 0x00
            if payload[6] == target:
                return
            payload[6] = target
            self._temperature_setting_event.clear()
            async with self.send_lock:
                if not self.connected or self.writer is None or self.writer.is_closing():
                    raise ConnectionError('CASA disconnected before temperature setting write')
                self._write_frame(make_temperature_setting_frame(payload))
                await asyncio.wait_for(self.writer.drain(), timeout=5)
            # The panel's ACK is not the source of truth: wait for 0x4D.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + TEMPERATURE_SETTING_CONFIRM_TIMEOUT_SECONDS
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError('CASA temperature setting not confirmed via 0x4D')
                try:
                    await asyncio.wait_for(self._temperature_setting_event.wait(), timeout=remaining)
                except asyncio.TimeoutError as exc:
                    raise TimeoutError('CASA temperature setting readback timed out') from exc
                if not self.connected or self.temperature_setting_data is None:
                    raise ConnectionError('CASA disconnected before temperature setting confirmation')
                if self.temperature_setting_data[6] == target:
                    _LOGGER.info('CASA temperature menu setting %s confirmed via 0x4D',
                                 'ON' if enabled else 'OFF')
                    return
                self._temperature_setting_event.clear()

    def _process_service_frame(self, frame):
        """Only accept full actual unit readback, never panel TX or ACK."""
        if frame[2:5] != b'\x85\xfd\x0a':
            return
        for key, (_tx, rx, size, _selector) in SERVICE_CONFIG.items():
            if frame[6] != rx:
                continue
            data = bytes(frame[9:-2])
            if len(data) != size:
                return
            self.service_settings[key] = data
            self._service_events[key].set()
            self.notify()
            # Shared 0x37 is used for Filter Monitor AND Weekly Schedule.
            continue

    def _process_week_frame(self, frame):
        if frame[2:5] != b'\x85\xfd\x0a':
            return
        cmd = frame[6]
        data = bytes(frame[9:-2])
        if cmd in WEEK_SLOT_READS and len(data) == 7:
            slot = WEEK_SLOT_READS.index(cmd)
            self.week_slots[slot] = data
            self._week_slot_events[slot].set()
            self.notify()
        elif cmd == 0x6F and len(data) == 1 and data[0] in (0x00, 0xFF):
            self.week_enabled = data[0] == 0xFF
            self._week_enabled_event.set()
            self.notify()

    def week_value(self, slot):
        return self.week_slots[slot] if self.connected and slot in range(4) else None

    async def _write_week_slot(self, slot, modify):
        self._require_writable()
        if slot not in range(4):
            raise ValueError('Invalid week program number')
        async with self._week_slot_locks[slot]:
            if not self.connected or self.writer is None or self.writer.is_closing():
                raise ConnectionError('CASA disconnected')
            event = self._week_slot_events[slot]
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), WEEK_CONFIRM_SECONDS)
            except asyncio.TimeoutError as exc:
                raise TimeoutError('No fresh CASA week program status') from exc
            old = self.week_value(slot)
            if old is None:
                raise ConnectionError('CASA week program status unavailable')
            new = bytearray(old)
            modify(new)
            new = bytes(new)
            if new == old:
                return
            # Preserve bit 7, which is set even when the weekday mask is empty.
            if not new[0] & 0x80:
                raise ValueError('CASA week program day header must retain bit 7')
            if new[1] > 23 or new[2] > 59 or new[3] > 23 or new[4] > 59:
                raise ValueError('Invalid week program time')
            frame = make_week_slot_frame(slot, new)
            event.clear()
            async with self.send_lock:
                if not self.connected or self.writer is None or self.writer.is_closing():
                    raise ConnectionError('CASA disconnected')
                self._write_frame(frame)
                await asyncio.wait_for(self.writer.drain(), 5)
            end = asyncio.get_running_loop().time() + WEEK_CONFIRM_SECONDS
            while self.connected:
                remaining = end - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    await asyncio.wait_for(event.wait(), remaining)
                except asyncio.TimeoutError:
                    break
                if self.week_value(slot) == new:
                    _LOGGER.info('CASA week program %d readback confirmed: %s', slot + 1, new.hex(' '))
                    return
                event.clear()
            raise TimeoutError(f'CASA week program {slot+1} not confirmed by readback')

    async def set_week_day(self, slot, weekday, enabled):
        self._require_writable()
        if weekday not in range(7):
            raise ValueError('Invalid weekday')
        mask = 1 << weekday
        def change(data):
            data[0] = (data[0] | mask) if enabled else (data[0] & ~mask)
        await self._write_week_slot(slot, change)

    async def set_week_time(self, slot, start, value):
        self._require_writable()
        if not (0 <= value.hour <= 23 and 0 <= value.minute <= 59):
            raise ValueError('Invalid program time')
        index = 1 if start else 3
        def change(data):
            data[index:index+2] = bytes((value.hour, value.minute))
        await self._write_week_slot(slot, change)

    async def set_week_temperature(self, slot, value):
        self._require_writable()
        if int(value) != value or not 13 <= value <= 20:
            raise ValueError('Week program temperature must be 13–20 °C, integer')
        await self._write_week_slot(slot, lambda data: data.__setitem__(5, int(value)))

    async def set_week_mode(self, slot, option):
        self._require_writable()
        if option not in WEEK_MODE_LABELS:
            raise ValueError('Invalid week ventilation mode')
        await self._write_week_slot(slot, lambda data: data.__setitem__(6, WEEK_MODE_LABELS[option]))

    async def set_week_enabled(self, enabled):
        self._require_writable()
        async with self._week_enabled_lock:
            if not self.connected or self.writer is None or self.writer.is_closing():
                raise ConnectionError('CASA disconnected')
            self._week_enabled_event.clear()
            try:
                await asyncio.wait_for(self._week_enabled_event.wait(), WEEK_CONFIRM_SECONDS)
            except asyncio.TimeoutError as exc:
                raise TimeoutError('No fresh CASA week ON/OFF status') from exc
            if self.week_enabled is enabled:
                return
            self._week_enabled_event.clear()
            async with self.send_lock:
                self._write_frame(make_week_enable_frame(enabled))
                await asyncio.wait_for(self.writer.drain(), 5)
            try:
                await asyncio.wait_for(self._week_enabled_event.wait(), WEEK_CONFIRM_SECONDS)
            except asyncio.TimeoutError as exc:
                raise TimeoutError('CASA weekly ON/OFF readback timeout') from exc
            if self.week_enabled is not enabled:
                raise TimeoutError('CASA weekly ON/OFF readback mismatch')

    def service_value(self, key):
        return self.service_settings.get(key) if self.connected else None

    async def _write_service(self, key, transform, *, selector=None):
        """Serialized fresh-read / single-field write / matching readback."""
        self._require_writable()
        async with self._service_locks[key]:
            if not self.connected or self.writer is None or self.writer.is_closing():
                raise ConnectionError('CASA TCP gateway disconnected')
            event = self._service_events[key]
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), SERVICE_FRESH_TIMEOUT_SECONDS)
            except asyncio.TimeoutError as exc:
                raise TimeoutError(f'No fresh {key} status received') from exc
            if not self.connected or self.service_settings[key] is None:
                raise ConnectionError('CASA disconnected while waiting for service status')
            old = bytes(self.service_settings[key])
            expected = bytearray(old)
            transform(expected)
            expected = bytes(expected)
            if expected == old:
                return
            frame = make_service_frame(key, expected, selector=selector)
            changed_indices = tuple(i for i, (a, b) in enumerate(zip(old, expected)) if a != b)
            event.clear()
            async with self.send_lock:
                if not self.connected or self.writer is None or self.writer.is_closing():
                    raise ConnectionError('CASA disconnected before service write')
                self._write_frame(frame)
                await asyncio.wait_for(self.writer.drain(), timeout=5)
            deadline = asyncio.get_running_loop().time() + SERVICE_VERIFY_TIMEOUT_SECONDS
            while True:
                if not self.connected:
                    raise ConnectionError('CASA disconnected during service confirmation')
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError(f'{key} not confirmed by CASA readback')
                try:
                    await asyncio.wait_for(event.wait(), remaining)
                except asyncio.TimeoutError as exc:
                    raise TimeoutError(f'{key} readback timed out') from exc
                observed = self.service_settings[key]
                if observed is not None and all(observed[i] == expected[i] for i in changed_indices):
                    _LOGGER.info('CASA service %s confirmed: %s', key, observed.hex(' '))
                    return
                event.clear()

    async def set_fan_percentage(self, key, level, percentage):
        self._require_writable()
        if key not in ('supply_fan', 'extract_fan') or level not in range(1, 6):
            raise ValueError('Invalid fan/level')
        if int(percentage) != percentage or not 20 <= percentage <= 100:
            raise ValueError('Fan percentage must be an integer 20–100')
        await self._write_service(key, lambda data: data.__setitem__(level - 1, int(percentage)))

    async def set_fan_profile(self, profile_index, level):
        self._require_writable()
        if profile_index not in range(6) or int(level) != level or level not in range(1, 6):
            raise ValueError('Fan profile level must be an integer 1–5')
        await self._write_service('fan_profiles', lambda data: data.__setitem__(profile_index, int(level)))

    async def disable_co2_control(self):
        # OFF only, never allow ON from HA; preserve both ppm thresholds.
        self._require_writable()
        await self._write_service('co2_control', lambda data: data.__setitem__(3, 0x01))

    async def disable_external_control(self):
        # Only clear externally correlated bit 0x02, preserving other flags.
        self._require_writable()
        await self._write_service('external_control', lambda data: data.__setitem__(0, data[0] & ~0x02))

    async def set_weekly_schedule(self, enabled):
        self._require_writable()
        if not enabled:
            await self._write_service('weekly_schedule', lambda data: data.__setitem__(3, 0x01))
            return

        # Force weekly menu VISIBILITY even if 0x37 currently reads 0x00,
        # is missing, or reports 0x02 already. Confirmed panel TX format:
        # 0x36 / selector 0x08 / ONE payload byte 0x02.
        async with self._service_locks['weekly_schedule']:
            if not self.connected or self.writer is None or self.writer.is_closing():
                raise ConnectionError('CASA TCP gateway disconnected')
            frame = make_service_frame('weekly_schedule', bytes((0, 0, 0, 2, 0, 0, 0, 0)))
            event = self._service_events['weekly_schedule']
            event.clear()
            async with self.send_lock:
                if not self.connected or self.writer is None or self.writer.is_closing():
                    raise ConnectionError('CASA disconnected before forced weekly menu write')
                self._write_frame(frame)
                await asyncio.wait_for(self.writer.drain(), timeout=5)
            _LOGGER.warning('CASA force weekly menu visible: sent 0x36 selector=0x08 value=0x02 frame=%s', frame.hex(' '))
            deadline = asyncio.get_running_loop().time() + SERVICE_VERIFY_TIMEOUT_SECONDS
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError('CASA forced weekly menu visibility not confirmed (0x37 byte[3] != 0x02)')
                try:
                    await asyncio.wait_for(event.wait(), remaining)
                except asyncio.TimeoutError as exc:
                    raise TimeoutError('CASA forced weekly menu visibility: no confirming 0x37') from exc
                data = self.service_settings.get('weekly_schedule')
                if data is not None and len(data) > 3 and data[3] == 0x02:
                    _LOGGER.info('CASA weekly menu visibility force confirmed by 0x37')
                    return
                event.clear()

    # --- Service -> Functions: field writes, preserving the other bytes. ---
    async def set_function_enabled(self, key, enabled):
        self._require_writable()
        fields = {
            'service_reminder': (1, 0x02),
            'summer_night_cooling': (0, 0x01),
            'heating': (0, 0x01),
            'filter_monitor': (0, 0x01),
            'fireplace_function': (3, 0x08),
            'boost_special': (1, 0x02),
            'electric_air_heater': (4, 0x10),
        }
        if key not in fields:
            raise ValueError(f'Unsupported Service -> Functions switch: {key}')
        index, selector = fields[key]
        await self._write_service(key, lambda data: data.__setitem__(index, 2 if enabled else 1), selector=selector)

    async def set_function_number(self, key, parameter, value):
        # Bounds are conservative UI limits, not manufacturer-certified ranges.
        self._require_writable()
        fields = {
            ('service_interval', 'months'): (0, 1, 24, 0x01),
            ('summer_night_cooling', 'temperature_difference'): (3, 0, 15, 0x08),
            ('summer_night_cooling', 'temperature_limit'): (2, 5, 25, 0x04),
            ('heating', 'temperature_limit'): (1, 10, 70, 0x02),
            ('heating', 'p'): (3, 0, 20, 0x08),
            ('heating', 'i'): (5, 0, 20, 0x08),
            ('heating', 'd'): (7, 0, 20, 0x08),
            ('filter_monitor', 'delay'): (1, 0, 240, 0x02),
            ('sa_limit', 'minimum_supply_temperature'): (0, 5, 25, 0x01),
            ('sa_limit', 'setpoint_difference'): (1, 0, 15, 0x02),
            ('electric_air_heater_temperature', 'temperature_setpoint'): (4, 5, 35, 0x10),
        }
        if (key, parameter) not in fields:
            raise ValueError(f'Unsupported function number: {key}/{parameter}')
        index, minimum, maximum, selector = fields[(key, parameter)]
        if not minimum <= value <= maximum:
            raise ValueError(f'{parameter} must be {minimum}..{maximum}')
        scaled = round(value * 100) if key == 'heating' and parameter in ('p', 'i', 'd') else int(value)
        if key != 'heating' or parameter not in ('p','i','d'):
            if int(value) != value:
                raise ValueError(f'{parameter} must be an integer')
        def mutate(data):
            if key == 'heating' and parameter in ('p', 'i', 'd'):
                data[index:index + 2] = scaled.to_bytes(2, 'big')
            else:
                data[index] = scaled
        await self._write_service(key, mutate, selector=selector)

    async def set_heating_control(self, option):
        self._require_writable()
        if option not in ('Supply', 'Extract'):
            raise ValueError('Heating control must be Supply or Extract')
        await self._write_service('heating', lambda data: data.__setitem__(2, 0 if option == 'Supply' else 1), selector=0x04)

    def _process_cooling_frame(self, frame):
        """Only trust the full 0x3D device readback, not a 0x3C ACK."""
        if frame[6] == 0x3D and frame[2:5] == b'\x85\xfd\x0a':
            data = frame[9:-2]
            if len(data) == 7:
                self.cooling_settings = bytes(data)
                self._cooling_last_seen = datetime.now(self._tz)
                self._cooling_status_event.set()
                self.notify()

    async def set_cooling_setting(self, *, temperature=None, fan=None):
        """Atomic read-modify-write, serialized, with device readback verification."""
        self._require_writable()
        if (temperature is None) == (fan is None):
            raise ValueError('Set exactly one summer cooling setting')
        if temperature is not None:
            if int(temperature) != temperature or not 13 <= temperature <= 20:
                raise ValueError('Temperature must be a whole number 13–20 C')
        elif fan not in COOLING_FAN_OPTIONS:
            raise ValueError(f'Unknown cooling fan option: {fan}')
        async with self._cooling_lock:
            if not self.connected or self.writer is None or self.writer.is_closing():
                raise ConnectionError('CASA TCP gateway is disconnected')
            # Wait for a NEW status frame, avoiding updates of stale settings.
            self._cooling_status_event.clear()
            try:
                await asyncio.wait_for(self._cooling_status_event.wait(), timeout=35)
            except asyncio.TimeoutError as exc:
                raise TimeoutError('No fresh CASA 0x3D cooling readback') from exc
            if self.cooling_settings is None:
                raise RuntimeError('CASA cooling settings unavailable')
            new_payload = bytearray(self.cooling_settings)
            if temperature is not None:
                new_payload[1] = int(temperature)
            else:
                new_payload[4] = COOLING_FAN_OPTIONS[fan]
            expected = bytes(new_payload)
            if expected == self.cooling_settings:
                return
            self._cooling_status_event.clear()
            async with self.send_lock:
                if not self.connected or self.writer is None or self.writer.is_closing():
                    raise ConnectionError('CASA disconnected before cooling write')
                self._write_frame(make_cooling_frame(expected, 0x02 if temperature is not None else 0x10))
                await asyncio.wait_for(self.writer.drain(), timeout=5)
            try:
                await asyncio.wait_for(self._cooling_status_event.wait(),
                                       timeout=COOLING_CONFIRM_TIMEOUT_SECONDS)
            except asyncio.TimeoutError as exc:
                _LOGGER.warning('CASA summer cooling change not confirmed (0x3D timeout)')
                raise TimeoutError('CASA summer cooling readback timed out') from exc
            if self.cooling_settings != expected:
                _LOGGER.warning('CASA summer cooling mismatch; expected=%s observed=%s',
                                expected.hex(' '), self.cooling_settings.hex(' '))
                raise RuntimeError('CASA returned different cooling settings')
            _LOGGER.info('CASA summer cooling confirmed: temp=%s fan=%s',
                         expected[1], COOLING_FAN_LABELS.get(expected[4], expected[4]))

    async def _send_command(self, frame, label):
        """Send one command with an already established pending transaction."""
        self._require_writable()
        generation = self._pending_generation
        self._pending_timeout_task = self.hass.async_create_background_task(
            self._mode_timeout(generation), 'CASA command confirmation timeout')
        try:
            self._write_frame(frame)
            await asyncio.wait_for(self.writer.drain(), timeout=5)
        except Exception:
            if generation == self._pending_generation:
                self._clear_pending()
                self.mode_sync_status = 'send_failed'
                self.notify()
            raise
        _LOGGER.info('CASA requested %s; awaiting 0x73 status', label)

    async def set_mode(self, option):
        """Select normal mode. Never bypass an active Fireplace overlay."""
        self._require_writable()
        if option not in MODE_PAYLOADS:
            raise ValueError(f'Unsupported CASA mode: {option}')
        async with self.send_lock:
            if not self.connected or self.writer is None or self.writer.is_closing():
                raise ConnectionError('CASA TCP gateway is disconnected')
            if self.fireplace_active is None:
                raise ValueError('CASA status is not yet known')
            if self.fireplace_active or self._pending_fireplace is not None:
                raise ValueError('Deaktiver peisfunksjonen med bryteren før du endrer modus')
            self._clear_pending()
            self.pending_mode = option
            self.mode_sync_status = 'pending'
            self.notify()
            await self._send_command(make_mode_frame(option), option)

    async def set_fireplace(self, enabled):
        """Toggle Fireplace only; CASA restores the underlying mode itself."""
        self._require_writable()
        async with self.send_lock:
            if not self.connected or self.writer is None or self.writer.is_closing():
                raise ConnectionError('CASA TCP gateway is disconnected')
            if self.fireplace_active is None:
                raise ValueError('CASA Fireplace status is not yet known')
            if self.fireplace_active == enabled and self._pending_fireplace is None:
                return
            self._clear_pending()
            self._pending_fireplace = enabled
            self.mode_sync_status = 'pending'
            self.notify()
            await self._send_command(
                make_fireplace_frame(enabled),
                f'Fireplace {"ON" if enabled else "OFF"}'
            )

    async def run(self):
        try:
            while True:
                writer = None
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(self.host, self.port), timeout=10)
                        
                    sock = writer.get_extra_info("socket")
                    if sock is not None:
                        sock.setsockopt(
                            socket.SOL_SOCKET,
                            socket.SO_KEEPALIVE, 1
                        )
                        sock.setsockopt(
                            socket.IPPROTO_TCP,
                            socket.TCP_KEEPIDLE, 60
                        )
                        sock.setsockopt(
                            socket.IPPROTO_TCP,
                            socket.TCP_KEEPINTVL, 30
                        )
                        sock.setsockopt(
                            socket.IPPROTO_TCP,
                            socket.TCP_KEEPCNT, 3
                        )
                        _LOGGER.info("CASA TCP keepalive enabled")
                        
                    self.writer = writer
                    self.parser = FrameParser()
                    self.values.clear()
                    self.clock_data = None
                    self.clock_observed_at = None
                    self._clock_status_event.clear()
                    self._clock_ack_event.clear()
                    self.temperature_setting_data = None
                    self.supply_air_setpoint_data = None
                    self._temperature_setting_event.clear()
                    self._supply_air_setpoint_event.clear()
                    self.cooling_settings = None
                    self._cooling_last_seen = None
                    self.week_slots = [None] * 4
                    self.week_enabled = None
                    for event in self._week_slot_events:
                        event.clear()
                    self._week_enabled_event.clear()
                    for key in SERVICE_CONFIG:
                        self.service_settings[key] = None
                        self._service_events[key].clear()
                    self._cooling_status_event.clear()
                    self._reset_mode_readback()
                    self.connected = True
                    self.quality.connection(True)
                    self.notify()
                    _LOGGER.info('CASA connected to %s:%s', self.host, self.port)
                    while True:
                        try:
                            chunk = await asyncio.wait_for(
                                reader.read(4096), timeout=RECEIVE_TIMEOUT_SECONDS)
                        except asyncio.TimeoutError:
                            _LOGGER.warning(
                                'CASA receive watchdog: no TCP data for %ss; reconnecting',
                                RECEIVE_TIMEOUT_SECONDS)
                            break
                        if not chunk:
                            _LOGGER.warning('CASA TCP stream closed; reconnecting')
                            break
                        before_crc = self.parser.crc_errors
                        frames = list(self.parser.feed(chunk))
                        crc_delta = self.parser.crc_errors - before_crc
                        changed = False
                        observed_keys = set()
                        for frame in frames:
                            decoded = decode(frame)
                            if decoded:
                                self.values.update(decoded)
                                observed_keys.update(decoded)
                                changed = True
                            self._process_service_frame(frame)
                            self._process_week_frame(frame)
                            if frame[6] == 0x4D:
                                self._process_temperature_setting_frame(frame)
                            if frame[6] == 0x3D:
                                self._process_cooling_frame(frame)
                            if frame[6] in (0x54, 0x55):
                                self._process_clock_frame(frame)
                            if frame[6] in (0x20, 0x30):
                                self._process_mode_response(frame)
                            elif frame[6] == 0x73:
                                self._process_mode_status(frame)
                        self.quality.receive(len(chunk), len(frames), crc_delta, observed_keys)
                        self.diagnostic_seq += 1
                        self.diagnostic_bytes += len(chunk)
                        self.diagnostic_frames += len(frames)
                        self.diagnostic_crc_errors += crc_delta
                        self.diagnostic_decoded += len(observed_keys)
                        self.diagnostic_events.append({
                            'seq': self.diagnostic_seq,
                            'timestamp': datetime.now(timezone.utc).isoformat(),
                            'bytes': len(chunk), 'frames': len(frames),
                            'crc_errors': crc_delta,
                            'raw_hex': chunk.hex(),
                            'sensor_keys': sorted(observed_keys),
                        })
                        # Quality and connection diagnostics update even when decoded values do not change.
                        self.notify()
                        await self._process_logging(frames)
                except asyncio.CancelledError:
                    raise
                except (OSError, asyncio.TimeoutError) as err:
                    _LOGGER.warning('CASA connection error: %s', err)
                except Exception:
                    _LOGGER.exception('Unexpected CASA receiver error')
                finally:
                    # Mark disconnected before awaiting socket shutdown, so
                    # concurrent mode writes cannot use the stale connection.
                    self.connected = False
                    self.quality.connection(False)
                    self.writer = None
                    self.values.clear()
                    self.clock_data = None
                    self.clock_observed_at = None
                    self.temperature_setting_data = None
                    self.supply_air_setpoint_data = None
                    self._temperature_setting_event.clear()
                    self._supply_air_setpoint_event.clear()
                    self.cooling_settings = None
                    self._cooling_last_seen = None
                    self.week_slots = [None] * 4
                    self.week_enabled = None
                    for event in self._week_slot_events:
                        event.set()
                    self._week_enabled_event.set()
                    for key in SERVICE_CONFIG:
                        self.service_settings[key] = None
                        self._service_events[key].set()
                    self._cooling_status_event.clear()
                    self._temperature_setting_event.set()
                    self._supply_air_setpoint_event.set()
                    self._reset_mode_readback()
                    self.notify()
                    if writer is not None:
                        writer.close()
                        try:
                            await asyncio.wait_for(writer.wait_closed(), timeout=5)
                        except (OSError, asyncio.TimeoutError):
                            pass
                _LOGGER.info('CASA reconnect attempt in %ss', RECONNECT_DELAY_SECONDS)
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)
        finally:
            if self._logging_was_on:
                try:
                    await self.hass.async_add_executor_job(self.protocol_logger.flush)
                except Exception:
                    _LOGGER.exception('CASA protocol logger final flush failed')


async def _async_start_hub(hass, host, port, config, entry=None):
    """Set up one read-only TCP receiver through YAML or a config entry."""
    if DOMAIN in hass.data:
        raise HomeAssistantError(
            "CASA Premium already configured; remove duplicate YAML/UI setup"
        )
    hub = CasaHub(hass, host, port)
    hub.baseline_store = Store(hass, 1, 'casa_premium_quality_baseline')
    stored_baseline = await hub.baseline_store.async_load()
    if isinstance(stored_baseline, dict) and isinstance(stored_baseline.get('sensor_intervals_ms'), dict):
        hub.quality.baseline = stored_baseline
        # Legacy baseline files have no verifiable calibration timestamp.
        hub.quality.calibrated_at = stored_baseline.get('calibrated_at')
        hub.quality.calibration_status = ('completed' if hub.quality.calibrated_at else
                                          'default' if stored_baseline.get('calibration_status') == 'default'
                                          else 'unknown')
    hass.data[DOMAIN] = hub
    try:
        if entry is None:
            await asyncio.gather(*(
                discovery.async_load_platform(hass, platform, DOMAIN, {}, config)
                for platform in READ_ONLY_PLATFORMS
            ))
        else:
            # Config-entry lifecycle requires forwarded platforms rather than
            # legacy discovery, otherwise their entities cannot be unloaded.
            await hass.config_entries.async_forward_entry_setups(
                entry, READ_ONLY_PLATFORMS
            )

        async def handle_sync_clock(call):
            await hub.sync_clock(force=call.data.get('force', False))

        # Compatibility service deliberately rejects all write attempts.
        hass.services.async_register(
            DOMAIN, 'sync_clock', handle_sync_clock,
            schema=vol.Schema({vol.Optional('force', default=False): cv.boolean}),
        )
        if not hass.data.get('casa_premium_quality_ws_registered'):
            @websocket_api.websocket_command({
                vol.Required('type'): 'casa_premium/quality',
                vol.Optional('action', default='status'): vol.In(
                    ['status', 'start', 'commit', 'reset']),
            })
            @websocket_api.async_response
            async def quality_ws(hass, connection, msg):
                active = hass.data.get(DOMAIN)
                if active is None:
                    connection.send_error(msg['id'], 'not_loaded', 'CASA integration not loaded')
                    return
                monitor = active.quality
                try:
                    action = msg['action']
                    if action == 'start':
                        monitor.start_calibration()
                    elif action == 'commit':
                        candidate = monitor.commit_calibration()
                        await active.baseline_store.async_save({**candidate, 'calibrated_at': monitor.calibrated_at})
                    elif action == 'reset':
                        monitor.reset_calibration()
                        await active.baseline_store.async_save({**monitor.baseline, 'calibration_status': 'default'})
                    if action != 'status':
                        active.notify()
                except ValueError as exc:
                    if msg['action'] == 'commit' and monitor.calibration_status == 'failed':
                        active.notify()
                    connection.send_error(msg['id'], 'calibration_rejected', str(exc))
                    return
                result = monitor.snapshot()
                result['calibration_state'] = (
                    'running' if monitor.calibration_started is not None else 'idle')
                result['calibration'] = monitor.snapshot()['calibration']
                connection.send_result(msg['id'], result)
            @websocket_api.websocket_command({
                vol.Required('type'): 'casa_premium/diagnostics',
                vol.Optional('after', default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
            })
            @websocket_api.async_response
            async def diagnostics_ws(hass, connection, msg):
                active = hass.data.get(DOMAIN)
                if active is None:
                    connection.send_error(msg['id'], 'not_loaded', 'CASA integration not loaded')
                    return
                events = active.diagnostic_events
                after = msg['after']
                oldest = events[0]['seq'] if events else active.diagnostic_seq + 1
                connection.send_result(msg['id'], {
                    'connected': active.connected,
                    'health': {
                        'quality': active.quality.snapshot(),
                        'received_bytes': active.diagnostic_bytes,
                        'valid_frames': active.diagnostic_frames,
                        'decoded_frames': active.diagnostic_decoded,
                        'crc_errors': active.diagnostic_crc_errors,
                    },
                    'latest_seq': active.diagnostic_seq,
                    'lost': max(0, oldest - after - 1) if after else 0,
                    'events': [e for e in events if e['seq'] > after],
                })
            websocket_api.async_register_command(hass, diagnostics_ws)
            websocket_api.async_register_command(hass, quality_ws)
            hass.data['casa_premium_quality_ws_registered'] = True
        hub.task = hass.async_create_background_task(
            hub.run(), 'CASA Premium TCP receiver'
        )
    except Exception:
        hass.data.pop(DOMAIN, None)
        raise
    return True


async def async_setup(hass, config):
    """Initialize installations with legacy YAML configuration."""
    if DOMAIN not in config:
        return True
    opts = config[DOMAIN]
    return await _async_start_hub(
        hass, opts[CONF_HOST], opts[CONF_PORT], config
    )


async def async_setup_entry(hass, entry):
    """Initialize a CASA TCP gateway from its GUI config entry."""
    settings = {**entry.data, **getattr(entry, 'options', {})}
    result = await _async_start_hub(
        hass, settings[CONF_HOST], settings[CONF_PORT], {}, entry=entry
    )
    if hasattr(entry, 'add_update_listener'):
        remove_listener = entry.add_update_listener(_async_entry_updated)
        if hasattr(entry, 'async_on_unload'):
            entry.async_on_unload(remove_listener)
    return result


async def _async_entry_updated(hass, entry):
    """Reload on successful Options save, closing the old TCP receiver."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    """Unload forwarded sensor platforms before closing the TCP receiver."""
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, READ_ONLY_PLATFORMS
    )
    if not unloaded:
        return False
    hub = hass.data.pop(DOMAIN, None)
    if hub is not None and hub.task is not None:
        hub.task.cancel()
        await asyncio.gather(hub.task, return_exceptions=True)
    hass.services.async_remove(DOMAIN, 'sync_clock')
    return True
