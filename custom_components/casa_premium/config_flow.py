"""UI-based setup and safe endpoint reconfiguration for CASA Premium."""
import asyncio
import ipaddress

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import config_validation as cv

from . import DOMAIN
from .decoder import FrameParser, decode

MIN_CONFIRM_SECONDS = 15
MAX_CONFIRM_SECONDS = 60


def _endpoint_schema(default_host="", default_port=8899):
    return vol.Schema({
        vol.Required(CONF_HOST, default=default_host): cv.string,
        vol.Required(CONF_PORT, default=default_port): cv.port,
    })


def _valid_host(host):
    """Accept IP literals and DNS names, never empty/whitespace values."""
    if not host or host != host.strip() or any(c.isspace() for c in host):
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return len(host) <= 253 and all(
            label and len(label) <= 63
            and label[0].isalnum() and label[-1].isalnum()
            and all(c.isalnum() or c == "-" for c in label)
            for label in host.split(".")
        )


async def _probe(host, port):
    """Only establish and close TCP; never transmit CASA commands."""
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5
        )
        writer.close()
        await asyncio.wait_for(writer.wait_closed(), timeout=5)
    except (OSError, asyncio.TimeoutError):
        return False
    return True


async def _confirm_casa(host, port, *, minimum=MIN_CONFIRM_SECONDS,
                        maximum=MAX_CONFIRM_SECONDS):
    """Passively validate CASA data within one bounded 15–60 s window.

    No commands are sent and no stored endpoint is changed. Cancellation
    propagates so Home Assistant can stop an abandoned validation task.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    deadline = started + maximum
    writer = None
    confirmed = False
    try:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=min(5, max(0, deadline - loop.time())),
            )
            parser = FrameParser()
            while loop.time() < deadline:
                try:
                    chunk = await asyncio.wait_for(
                        reader.read(4096), timeout=max(0, deadline - loop.time())
                    )
                except asyncio.TimeoutError:
                    break
                if not chunk:
                    break
                if any(decode(frame) for frame in parser.feed(chunk)):
                    confirmed = True
                    break
        except (OSError, asyncio.TimeoutError, ValueError):
            confirmed = False
        # Even an immediate TCP refusal remains Pending for at least 15 s.
        remaining_minimum = started + minimum - loop.time()
        if remaining_minimum > 0:
            await asyncio.sleep(remaining_minimum)
        return confirmed
    finally:
        if writer is not None:
            writer.close()
            # Socket cleanup must not extend the 60-second validation window.
            remaining = deadline - loop.time()
            if remaining > 0:
                try:
                    await asyncio.wait_for(writer.wait_closed(), timeout=remaining)
                except (OSError, asyncio.TimeoutError):
                    pass


class CasaPremiumConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a CASA TCP gateway using Home Assistant UI."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            if not _valid_host(host):
                errors["base"] = "invalid_host"
            elif not await _confirm_casa(host, port):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"CASA Premium ({host})", data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=_endpoint_schema(), errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return CasaPremiumOptionsFlow(config_entry)


class CasaPremiumOptionsFlow(config_entries.OptionsFlow):
    """Validate a candidate in HA's cancellable progress UI before saving."""

    def __init__(self, config_entry):
        self._entry = config_entry
        self._candidate = None
        self._validation_task = None

    def _status_placeholder(self, *, candidate_failed=False):
        """Show four readable diagnostic rows, never stale OK for a failed IP."""
        labels = (
            ("TCP/IP", "tcp"),
            ("Serial bytes", "raw_bytes"),
            ("CASA telegrams", "telegram"),
            ("Fresh sensor data", "sensors"),
        )
        icons = {"ok": "🟢", "degraded": "🟡", "error": "🔴",
                 "waiting": "⚪", "not_measurable": "⚪"}
        if candidate_failed:
            # A candidate may fail after TCP succeeds. Do not invent which
            # individual stage failed without collecting candidate telemetry.
            return "\\n\\n".join(
                f"⚪ {label}: not confirmed" for label, _ in labels
            )
        hub = self.hass.data.get(DOMAIN)
        if hub is None or not hasattr(hub, "diagnostic_health"):
            return "\\n\\n".join(
                f"⚪ {label}: waiting" for label, _ in labels
            )
        states = hub.diagnostic_health()
        return "\\n\\n".join(
            f"{icons.get(states.get(key), '⚪')} {label}: {states.get(key, 'waiting')}"
            for label, key in labels
        )

    async def async_step_init(self, user_input=None):
        current = {**self._entry.data, **self._entry.options}
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=_endpoint_schema(
                    current.get(CONF_HOST, ""), current.get(CONF_PORT, 8899)
                ),
                description_placeholders={"connection_status": self._status_placeholder()},
            )
        host, port = user_input[CONF_HOST], user_input[CONF_PORT]
        if not _valid_host(host):
            return self.async_show_form(
                step_id="init",
                data_schema=_endpoint_schema(host, port),
                description_placeholders={"connection_status": self._status_placeholder()},
                errors={"base": "invalid_host"},
            )
        if (host, port) == (current[CONF_HOST], current[CONF_PORT]):
            return self.async_create_entry(title="", data={})
        self._candidate = dict(user_input)
        self._validation_task = self.hass.async_create_task(_confirm_casa(host, port))
        return await self.async_step_pending()

    async def async_step_pending(self, user_input=None):
        """Native HA progress dialog; Cancel aborts the flow without saving."""
        if self._validation_task is None:
            return self.async_abort(reason="unknown")
        if not self._validation_task.done():
            return self.async_show_progress(
                step_id="pending",
                progress_action="validate_connection",
                progress_task=self._validation_task,
            )
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_finish(self, user_input=None):
        """Only commit options after a decoded CASA telegram was observed."""
        task = self._validation_task
        if task is None:
            return self.async_abort(reason="unknown")
        try:
            confirmed = task.result()
        except (asyncio.CancelledError, OSError, ValueError):
            confirmed = False
        if confirmed:
            return self.async_create_entry(title="", data=self._candidate)
        return await self.async_step_save_anyway()

    async def async_step_save_anyway(self, user_input=None):
        """Only explicit confirmation saves a failed candidate endpoint."""
        if self._candidate is None:
            return self.async_abort(reason="unknown")
        if user_input is not None:
            return self.async_create_entry(title="", data=self._candidate)
        return self.async_show_form(
            step_id="save_anyway",
            data_schema=vol.Schema({}),
            description_placeholders={
                "host": self._candidate[CONF_HOST],
                "port": str(self._candidate[CONF_PORT]),
                "connection_status": self._status_placeholder(candidate_failed=True),
            },
        )
