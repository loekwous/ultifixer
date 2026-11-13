"""Test-only Cura plugin that drives a real Cura through Ultifixer scenarios.

It is never shipped. The e2e runner copies it into Cura's plugin folder and sets
ULTIFIXER_E2E_PLAN (a JSON file) and ULTIFIXER_E2E_OUT (a results folder).
"""


def getMetaData():
    return {}


def register(app):
    from .Driver import Driver
    return {"extension": Driver()}
