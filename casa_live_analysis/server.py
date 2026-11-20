"""CASA Live Analysis add-on: ingress-only read-only diagnostic bridge."""
import asyncio
import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from analysis import analyze, calibrate, DEFAULT_BASELINE
from capture import Capture

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger("casa-live")
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
# Prefer the documented Supervisor proxy; use internal Core DNS as fallback.
UPSTREAMS = (
    "ws://supervisor/core/api/websocket",
    "ws://homeassistant:8123/api/websocket",
    "ws://homeassistant:80/api/websocket",
)
MAX_EVENTS = 12000
PAGE_SIZE = 200
BASELINE_FILE = Path('/data/baseline.json')

def read_baseline():
    try:
        return json.loads(BASELINE_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return dict(DEFAULT_BASELINE)

baseline = read_baseline()
calibration = {'started': None, 'events': deque(maxlen=250000), 'state': 'idle', 'message': ''}



class State:
    def __init__(self):
        self.events = deque(maxlen=MAX_EVENTS)
        self.last_seq = 0
        self.upstream_lost = 0
        self.data_completeness = 'unknown'
        self.health = {}
        self.connected = False
        self.api_connected = False
        self.error = "Connecting to Home Assistant diagnostics API"
        self.last_poll_utc = None

    def snapshot(self, after=0):
        oldest = self.events[0]["seq"] if self.events else self.last_seq + 1
        return {
            "api_connected": self.api_connected,
            "connected": self.connected,
            "error": self.error,
            "health": self.health,
            "last_poll_utc": self.last_poll_utc,
            "latest_seq": self.last_seq,
            "upstream_lost": self.upstream_lost,
            "data_completeness": self.data_completeness,
            "lost": max(0, oldest - after - 1) if after else 0,
            "events": [e for e in self.events if e["seq"] > after],
        }


state = State()
capture = Capture()


async def consume_ws(session, url):
    LOG.info("Connecting to HA websocket: %s", url)
    async with session.ws_connect(url, heartbeat=30, timeout=15, max_msg_size=16 * 1024 * 1024) as ws:
        hello = await ws.receive_json(timeout=15)
        if hello.get("type") != "auth_required":
            raise RuntimeError("Expected auth_required, got " + str(hello.get("type")))
        await ws.send_json({"type": "auth", "access_token": TOKEN})
        auth = await ws.receive_json(timeout=15)
        if auth.get("type") != "auth_ok":
            raise RuntimeError("HA authentication failed: " + str(auth.get("type")))
        state.api_connected = True
        state.error = None
        request_id = 0
        while True:
            request_id += 1
            await ws.send_json({
                "id": request_id,
                "type": "casa_premium/diagnostics",
                "after": state.last_seq,
                "limit": PAGE_SIZE,
            })
            reply = await ws.receive_json(timeout=15)
            if reply.get("type") != "result" or reply.get("id") != request_id:
                raise RuntimeError("Unexpected diagnostics API response")
            if not reply.get("success"):
                raise RuntimeError("CASA API: " + json.dumps(reply.get("error", {})))
            result = reply.get("result", {})
            state.connected = bool(result.get("connected"))
            state.health = result.get("health", {})
            state.last_poll_utc = datetime.now(timezone.utc).isoformat()
            if result.get("lost"):
                state.upstream_lost += int(result["lost"])
                state.data_completeness = "incomplete"
            elif state.data_completeness == "unknown":
                state.data_completeness = "complete"
            state.error = (f"HA event buffer lost {state.upstream_lost} events"
                           if state.upstream_lost else None)
            for event in result.get("events", []):
                seq = event.get("seq")
                if not isinstance(seq, int) or seq <= state.last_seq:
                    continue
                event = {**event, 'utc': event.get('timestamp'), 'kind': 'tcp_receive',
                         'keys': event.get('sensor_keys', [])}
                state.events.append(event)
                capture.append(event)
                if calibration['state'] == 'running':
                    calibration['events'].append(event)
                state.last_seq = seq
            # Drain bounded pages before waiting; resume from the last confirmed seq.
            if not result.get("has_more"):
                await asyncio.sleep(1)


async def poll_forever(app):
    if not TOKEN:
        state.error = "SUPERVISOR_TOKEN unavailable: enable homeassistant_api"
        LOG.error(state.error)
        return
    timeout = ClientTimeout(total=None, sock_connect=15)
    async with ClientSession(timeout=timeout) as session:
        while True:
            for url in UPSTREAMS:
                try:
                    await consume_ws(session, url)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    state.api_connected = False
                    state.connected = False
                    state.error = str(exc)
                    LOG.warning("%s: %s", url, exc)
            await asyncio.sleep(5)


async def index(request):
    return web.FileResponse(Path(__file__).with_name("index.html"))


async def diagnostics(request):
    try:
        after = int(request.query.get("after", "0"))
        if after < 0:
            raise ValueError
    except ValueError:
        raise web.HTTPBadRequest(text="after must be nonnegative integer")
    return web.json_response(state.snapshot(after))


async def integration_quality(action='status'):
    async with ClientSession(timeout=ClientTimeout(total=20)) as session:
        last_error = None
        for url in UPSTREAMS:
            try:
                async with session.ws_connect(url, heartbeat=15) as ws:
                    await ws.receive_json(timeout=10)
                    await ws.send_json({'type': 'auth', 'access_token': TOKEN})
                    auth = await ws.receive_json(timeout=10)
                    if auth.get('type') != 'auth_ok':
                        raise RuntimeError('HA authentication rejected')
                    await ws.send_json({'id': 1, 'type': 'casa_premium/quality', 'action': action})
                    result = await ws.receive_json(timeout=10)
                    if not result.get('success'):
                        raise RuntimeError(str(result.get('error')))
                    return result['result']
            except Exception as exc:
                last_error = exc
        raise RuntimeError('CASA quality API unavailable: ' + str(last_error))


async def analysis_report(request):
    report = analyze(list(state.events), baseline=baseline, connected=state.connected)
    try:
        shared = await integration_quality()
        report['quality'] = {key: shared[key] for key in ('tcp', 'crc', 'sensor')}
        report['quality_source'] = 'integration'
    except RuntimeError as exc:
        report['quality'] = {key: {'status': 'unknown'} for key in ('tcp', 'crc', 'sensor')}
        report['quality_source'] = 'unavailable'
        report['quality_error'] = str(exc)
    return web.json_response(report)


async def capture_status(request):
    return web.json_response(capture.snapshot())


async def capture_action(request):
    action = (await request.json()).get('action')
    try:
        if action == 'start':
            capture.start()
        elif action == 'stop':
            capture.stop()
        else:
            raise web.HTTPBadRequest(text='Invalid capture action')
    except (OSError, ValueError) as exc:
        raise web.HTTPConflict(text=str(exc))
    return web.json_response(capture.snapshot())


async def capture_download(request):
    if not capture.file.is_file():
        raise web.HTTPNotFound(text='No saved capture')
    return web.FileResponse(capture.file, headers={'Content-Disposition': 'attachment; filename="casa-last-capture.csv"'})


async def baseline_status(request):
    try:
        shared = await integration_quality()
    except RuntimeError as exc:
        raise web.HTTPServiceUnavailable(text=str(exc))
    return web.json_response({'baseline': shared.get('baseline'), 'source': 'integration',
                              'calibration_state': shared.get('calibration_state'),
                              'calibration': shared.get('calibration')})


async def baseline_action(request):
    action = (await request.json()).get('action')
    if action not in ('start', 'commit', 'reset'):
        raise web.HTTPBadRequest(text='Invalid action')
    try:
        shared = await integration_quality(action)
    except RuntimeError as exc:
        raise web.HTTPServiceUnavailable(text=str(exc))
    return web.json_response({'baseline': shared.get('baseline'), 'source': 'integration',
                              'calibration_state': shared.get('calibration_state'),
                              'calibration': shared.get('calibration')})


async def on_start(app):
    app["poll_task"] = asyncio.create_task(poll_forever(app))


async def on_cleanup(app):
    task = app["poll_task"]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


app = web.Application(client_max_size=1024 * 1024)
app.router.add_get("/", index)
app.router.add_get("/api/diagnostics", diagnostics)
app.router.add_get("/api/analysis", analysis_report)
app.router.add_get("/api/capture", capture_status)
app.router.add_post("/api/capture", capture_action)
app.router.add_get("/api/capture/download", capture_download)
app.router.add_get("/api/baseline", baseline_status)
app.router.add_post("/api/baseline", baseline_action)
app.on_startup.append(on_start)
app.on_cleanup.append(on_cleanup)
if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8099, access_log=None)
