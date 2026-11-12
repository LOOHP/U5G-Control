"""Constants for the U5G Control integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "u5g_control"
NAME = "U5G Control"
VERSION = "0.1.27"

PLATFORMS = ["sensor", "binary_sensor", "switch", "button"]

CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_HOST_KEY = "host_key"
CONF_LTE_BANDS = "lte_bands"
CONF_SA_BANDS = "sa_bands"
CONF_NSA_BANDS = "nsa_bands"
CONF_DISABLED_BAND = "disabled_band"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_AUTO_REAPPLY = "auto_reapply"
CONF_FORGET_SIMS = "forget_sims"

DEFAULT_PORT = 22
DEFAULT_DISABLED_BAND = 79
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_UPDATE_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

STORE_VERSION = 1
STORE_KEY_PREFIX = "u5g_control"

MODE_5G = "5gnr"
MODE_LTE = "lte"
MODE_5G_LTE = "5gnr,lte"

MODEM_COMMAND_TIMEOUT = 15

