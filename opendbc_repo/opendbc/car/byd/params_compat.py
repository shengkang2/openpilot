#!/usr/bin/env python3
# Compatibility shim: the BYD port reads runtime toggles from openpilot's
# Params store (device-only). When opendbc is used standalone (unit tests,
# CI), fall back to safe defaults so imports never fail.

try:
  from openpilot.common.params import Params  # noqa: F401
except Exception:

  class _ParamsFallback:
    def get_bool(self, key, default=False):
      return default

    def get_int(self, key, default=0):
      return default

    def get(self, key, encoding=None):
      return None

    def put(self, key, value):
      pass

  Params = _ParamsFallback
