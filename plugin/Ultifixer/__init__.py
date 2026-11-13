# Copyright (c) 2026 Loek Lankhorst. Released under the MIT license.
"""Ultifixer: prints MakerWorld / Bambu Lab vases hollow in Cura by switching on vase mode."""


def getMetaData():
    return {}


def register(app):
    from .Ultifixer import Ultifixer  # imported here so the pure modules stay testable without Cura
    return {"extension": Ultifixer()}
