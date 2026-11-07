"""BP hotfix (2026-10-29, deployed via SSH by xiaowang):

params_pyx.so was built against an outdated params key table (params.o from
the stock AGNOS build), so newer keys like "Blendful" raise UnknownKeyName
and crash every process that touches them (UI restart loop on boot).

This shim swaps common.params_pyx.Params for a tolerant subclass: unknown
keys log a warning and return the type default instead of raising.
Remove once params_pyx.so is rebuilt against the current params_keys.h.
"""
import common.params_pyx as _pyx

_UnknownKeyName = _pyx.UnknownKeyName
_BaseParams = _pyx.Params


class Params(_BaseParams):
    def get(self, *args, **kwargs):
        try:
            return super().get(*args, **kwargs)
        except _UnknownKeyName:
            print(f"params_compat: unknown key ignored (get): {args!r}")
            return None

    def get_bool(self, *args, **kwargs):
        try:
            return super().get_bool(*args, **kwargs)
        except _UnknownKeyName:
            print(f"params_compat: unknown key ignored (get_bool): {args!r}")
            return False

    def put(self, *args, **kwargs):
        try:
            return super().put(*args, **kwargs)
        except _UnknownKeyName:
            print(f"params_compat: unknown key ignored (put): {args!r}")

    def put_bool(self, *args, **kwargs):
        try:
            return super().put_bool(*args, **kwargs)
        except _UnknownKeyName:
            print(f"params_compat: unknown key ignored (put_bool): {args!r}")


_pyx.Params = Params
