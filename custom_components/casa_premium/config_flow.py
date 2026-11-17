"""UI-based setup and safe endpoint reconfiguration for CASA Premium."""
import asyncio
import ipaddress

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import config_validation as cv

from . import DOMAIN


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
            elif not await _probe(host, port):
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
    """Change the TCP endpoint without losing the last working settings."""

    def __init__(self, config_entry):
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        errors = {}
        current = {**self._entry.data, **self._entry.options}
        if user_input is not None:
            host, port = user_input[CONF_HOST], user_input[CONF_PORT]
            if not _valid_host(host):
                errors["base"] = "invalid_host"
            elif (host, port) != (current[CONF_HOST], current[CONF_PORT]):
                if not await _probe(host, port):
                    errors["base"] = "cannot_connect"
            if not errors:
                return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_endpoint_schema(
                current.get(CONF_HOST, ""), current.get(CONF_PORT, 8899)
            ),
            errors=errors,
        )
