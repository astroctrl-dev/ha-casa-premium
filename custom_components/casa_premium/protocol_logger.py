"""Passive CASA frame recorder. All methods doing file I/O run in an executor."""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


class ProtocolLogger:
    def __init__(self, config_dir):
        # No filesystem access in the constructor (HA event loop safe).
        self.directory = Path(config_dir)
        self.registry_path = self.directory / 'casa_messages.json'
        self.traffic_path = self.directory / 'casa_traffic.log'
        self.changes_path = self.directory / 'casa_changes.log'
        self.messages = {}
        self.next_id = 1
        self.loaded = False
        self.dirty = False

    def load(self):
        """Run in executor before recording. Preserve user classifications."""
        if self.loaded:
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding='utf-8'))
            messages = data.get('messages', {})
            if not isinstance(messages, dict):
                raise ValueError('messages must be an object')
            self.messages = messages
            ids = []
            for entry in messages.values():
                try:
                    ids.append(int(entry.get('id', 'MSG-000').split('-')[-1]))
                except (ValueError, TypeError, AttributeError):
                    pass
            self.next_id = max(ids, default=0) + 1
        except FileNotFoundError:
            pass
        except (ValueError, OSError, TypeError, AttributeError) as exc:
            _LOGGER.warning('CASA registry cannot be loaded: %s', exc)
            # Do not overwrite an unreadable registry.
            raise
        self.loaded = True

    def _save(self):
        temp = self.registry_path.with_suffix('.json.tmp')
        temp.write_text(json.dumps({'version': 1, 'messages': self.messages},
                                   indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        os.replace(temp, self.registry_path)
        self.dirty = False

    @staticmethod
    def _append(path, line):
        if path.exists() and path.stat().st_size > 5 * 1024 * 1024:
            backup = path.with_suffix(path.suffix + '.1')
            os.replace(path, backup)
        with path.open('a', encoding='utf-8') as out:
            out.write(line + '\n')

    def start_new_session(self):
        """Start fresh traffic logs, preserving the message registry."""
        self.load()
        self.flush()
        self.traffic_path.write_text('', encoding='utf-8')
        self.changes_path.write_text('', encoding='utf-8')


    def record(self, frame):
        if not self.loaded:
            raise RuntimeError('CASA logger not loaded')
        now = datetime.now().astimezone().isoformat(timespec='milliseconds')
        cmd = frame[6]
        payload = frame[9:-2]
        key = f'{frame[2:5].hex().upper()}:{cmd:02X}'
        hex_payload = payload.hex(' ').upper()
        entry = self.messages.get(key)
        is_new = entry is None
        if is_new:
            entry = {'id': f'MSG-{self.next_id:03d}', 'command': f'0x{cmd:02X}',
                     'header_2_4': frame[2:5].hex(' ').upper(),
                     'status': 'NEW', 'description': '', 'first_seen': now,
                     'last_seen': now, 'count': 0, 'variants': {}}
            self.next_id += 1
            self.messages[key] = entry
        entry['last_seen'] = now
        entry['count'] = entry.get('count', 0) + 1
        variants = entry.setdefault('variants', {})
        new_variant = hex_payload not in variants
        if new_variant:
            variants[hex_payload] = {'first_seen': now, 'last_seen': now, 'count': 0}
        variants[hex_payload]['last_seen'] = now
        variants[hex_payload]['count'] += 1
        self.dirty = True
        self._append(self.traffic_path,
                     f'{now} {entry["id"]} CMD=0x{cmd:02X} FRAME={frame.hex(" ").upper()} DATA={hex_payload}')
        if is_new or new_variant:
            event = 'NEW_MESSAGE' if is_new else 'NEW_VARIANT'
            self._append(self.changes_path,
                         f'{now} {event} {entry["id"]} CMD=0x{cmd:02X} DATA={hex_payload}')
            self._save()

    def flush(self):
        if self.loaded and self.dirty:
            self._save()
