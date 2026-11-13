# Copyright (c) 2026 Loek Lankhorst. Released under the MIT license.
"""Cura side of Ultifixer: watch opened files and switch on vase mode for solid vases."""

import os
from typing import Dict, List, Optional, Tuple

import numpy
from PyQt6.QtCore import QObject

from UM.Extension import Extension
from UM.Job import Job
from UM.Logger import Logger
from UM.Message import Message
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator

from cura.CuraApplication import CuraApplication

from .project_settings import VaseSourceSettings, read_3mf_settings
from .vase_settings import VasePlan, make_plan
from .vase_shape import ShapeReport, analyse_mesh

PREF_AUTO = "ultifixer/auto_detect"
_MISSING = object()


def _mesh_arrays(node) -> Tuple[Optional[numpy.ndarray], Optional[numpy.ndarray]]:
    """All triangles under a scene node, in world coordinates (Y is up in Cura)."""
    vertex_blocks = []
    index_blocks = []
    offset = 0
    indexed = True
    for child in DepthFirstIterator(node):
        mesh = child.getMeshData()
        if mesh is None or mesh.getVertices() is None or len(mesh.getVertices()) == 0:
            continue
        matrix = numpy.asarray(child.getWorldTransformation(copy=True).getData(), dtype=numpy.float64)
        local = numpy.asarray(mesh.getVertices(), dtype=numpy.float64)
        vertices = local @ matrix[:3, :3].T + matrix[:3, 3]
        indices = mesh.getIndices()
        if indices is None:
            indexed = False
        vertex_blocks.append((numpy.asarray(vertices), None if indices is None else numpy.asarray(indices)))
    if not vertex_blocks:
        return None, None
    if not indexed:
        flat = [v if i is None else v[i.reshape(-1)] for v, i in vertex_blocks]
        return numpy.concatenate(flat), None
    for vertices, indices in vertex_blocks:
        index_blocks.append(indices + offset)
        offset += len(vertices)
    return numpy.concatenate([v for v, _ in vertex_blocks]), numpy.concatenate(index_blocks)


class _AnalyseJob(Job):
    """Runs the shape analysis away from the user interface thread."""

    def __init__(self, meshes: List[Tuple[object, numpy.ndarray, Optional[numpy.ndarray]]], file_name: str) -> None:
        super().__init__()
        self._meshes = meshes
        self._file_name = file_name

    def run(self) -> None:
        reports = []
        for node, vertices, indices in self._meshes:
            try:
                reports.append((node, analyse_mesh(vertices, indices, up=1, file_name=self._file_name)))
            except Exception:  # never let a weird mesh break Cura
                Logger.logException("w", "Ultifixer: shape analysis failed for %s", self._file_name)
                reports.append((node, ShapeReport(reasons=["analysis failed"])))
        self.setResult(reports)


class Ultifixer(QObject, Extension):
    def __init__(self, parent=None) -> None:
        QObject.__init__(self, parent)
        Extension.__init__(self)
        self._app = CuraApplication.getInstance()
        self._app.getPreferences().addPreference(PREF_AUTO, True)

        self.setMenuName("Ultifixer")
        self.addMenuItem("Maak er een vaas van", self.makeSelectionVase)
        self.addMenuItem("Vaasmodus uitzetten", self.undoVaseMode)
        self.addMenuItem("Automatisch herkennen aan/uit", self.toggleAutoDetect)

        self._nodes_before: Dict[str, set] = {}
        self._vase_nodes: List[object] = []
        self._saved_values: List[Tuple[object, str, object]] = []
        self._message: Optional[Message] = None
        self._jobs: Dict[_AnalyseJob, str] = {}
        self.busy = 0  # number of files still being analysed (used by the tests)
        self.events: List[Dict[str, object]] = []  # what happened, newest last (used by the tests)

        self._app.fileLoaded.connect(self._onFileLoaded)
        self._app.fileCompleted.connect(self._onFileCompleted)
        self._app.getController().getScene().sceneChanged.connect(self._onSceneChanged)
        Logger.log("i", "Ultifixer: loaded, automatic vase detection is %s", "on" if self.autoDetect else "off")

    # ----------------------------------------------------------------- state

    @property
    def autoDetect(self) -> bool:
        value = self._app.getPreferences().getValue(PREF_AUTO)
        return value not in (False, "False", "false", 0, "0")

    @property
    def isActive(self) -> bool:
        return bool(self._saved_values)

    def _sliceableNodes(self):
        root = self._app.getController().getScene().getRoot()
        return [n for n in DepthFirstIterator(root) if n.callDecoration("isSliceable")]

    def _topLevel(self, nodes):
        """Keep only nodes whose parent is not in the list (3MF groups load as a parent with children)."""
        ids = {id(n) for n in nodes}
        return [n for n in nodes if id(n.getParent()) not in ids]

    def _record(self, kind: str, **details) -> None:
        details["event"] = kind
        self.events.append(details)
        Logger.log("i", "Ultifixer: %s %s", kind, details)

    # ------------------------------------------------------------ file hooks

    def _onFileLoaded(self, file_name: str) -> None:
        self._nodes_before[file_name] = {id(n) for n in self._sliceableNodes()}

    def _onFileCompleted(self, file_name: str) -> None:
        before = self._nodes_before.pop(file_name, set())
        new_nodes = self._topLevel([n for n in self._sliceableNodes() if id(n) not in before])
        if not new_nodes:
            return
        if not self.autoDetect:
            self._record("skipped", file=os.path.basename(file_name), reason="automatic detection is off")
            return

        if file_name.lower().endswith(".3mf"):
            source = read_3mf_settings(file_name)
            if source.slicer:
                if source.spiral_mode:
                    self._apply(new_nodes, source, os.path.basename(file_name),
                                "het bestand zegt: vaasmodus (%s)" % ("Bambu Studio" if source.slicer == "bambu" else "PrusaSlicer"),
                                automatic=True)
                else:
                    self._record("not_vase", file=os.path.basename(file_name), reason="3MF has vase mode off")
                    self._warnIfMixed(new_nodes)
                return

        # No slicer settings: look at the shape.
        meshes = []
        for node in new_nodes:
            vertices, indices = _mesh_arrays(node)
            if vertices is not None:
                meshes.append((node, vertices, indices))
        if not meshes:
            return
        self.busy += 1
        job = _AnalyseJob(meshes, file_name)
        # UM signals hold weak references to plain functions, so connect a bound method
        # and keep the job alive here until it reports back.
        self._jobs[job] = file_name
        job.finished.connect(self._onJobFinished)
        job.start()

    def _onJobFinished(self, job: _AnalyseJob) -> None:
        # Signals emitted from the worker thread arrive here on the main thread.
        self._app.callLater(self._onAnalysed, job)

    def _onAnalysed(self, job: _AnalyseJob) -> None:
        file_name = self._jobs.pop(job, "")
        self.busy = max(0, self.busy - 1)
        reports = job.getResult() or []
        vases = [node for node, report in reports if report.looks_like_vase and node.getParent() is not None]
        for node, report in reports:
            Logger.log("i", "Ultifixer: shape of %s: %s", os.path.basename(file_name), report.summary())
        if vases:
            self._apply(vases, None, os.path.basename(file_name), "de vorm is een dichte vaas", automatic=True)
        else:
            reasons = "; ".join(r.reasons[0] for _, r in reports if r.reasons)
            self._record("not_vase", file=os.path.basename(file_name), reason=reasons)
            self._warnIfMixed([node for node, _ in reports])

    def _onSceneChanged(self, _changed=None) -> None:
        if not self._vase_nodes:
            return
        still_there = [n for n in self._vase_nodes if n.getParent() is not None and n.callDecoration("isSliceable")]
        if len(still_there) != len(self._vase_nodes):
            self._vase_nodes = still_there
        if not still_there and self.isActive:
            self._restore()
            self._record("restored", reason="vase removed from the build plate")
            self._show("Er staat geen vaas meer op het bed. De gewone instellingen zijn terug.",
                       "Vaasmodus uit", lifetime=10)

    # --------------------------------------------------------- menu actions

    def makeSelectionVase(self) -> None:
        from UM.Scene.Selection import Selection
        nodes = self._topLevel([n for n in Selection.getAllSelectedObjects() if n.callDecoration("isSliceable")])
        if not nodes:
            nodes = self._topLevel(self._sliceableNodes())
        if not nodes:
            self._show("Open eerst een vaas, en kies dan opnieuw Maak er een vaas van.", "Geen model", lifetime=15)
            return
        name = nodes[0].getName() if len(nodes) == 1 else "%d modellen" % len(nodes)
        self._apply(nodes, None, name, "je koos Maak er een vaas van", automatic=False)

    def undoVaseMode(self) -> None:
        if not self.isActive:
            self._show("De vaasmodus van Ultifixer staat al uit.", "Vaasmodus uit", lifetime=10)
            return
        self._restore()
        self._vase_nodes = []
        self._record("restored", reason="user")
        self._show("De gewone instellingen zijn terug.", "Vaasmodus uit", lifetime=10)

    def toggleAutoDetect(self) -> None:
        new_value = not self.autoDetect
        self._app.getPreferences().setValue(PREF_AUTO, new_value)
        self._record("auto_detect", enabled=new_value)
        if new_value:
            self._show("Ultifixer herkent vazen weer automatisch.", "Automatisch aan", lifetime=10)
        else:
            self._show("Ultifixer doet niets meer vanzelf. Via Extensies > Ultifixer > Maak er een vaas van "
                       "kun je het nog steeds zelf doen.", "Automatisch uit", lifetime=15)

    # ------------------------------------------------------- settings work

    def _nozzleFor(self, nodes) -> float:
        stack = self._app.getGlobalContainerStack()
        extruders = stack.extruderList if stack else []
        position = 0
        try:
            value = nodes[0].callDecoration("getActiveExtruderPosition")
            if value is not None:
                position = int(value)
        except (TypeError, ValueError, IndexError):
            position = 0
        if not extruders:
            return 0.4
        extruder = extruders[position] if position < len(extruders) else extruders[0]
        try:
            return float(extruder.getProperty("machine_nozzle_size", "value"))
        except (TypeError, ValueError):
            return 0.4

    def _set(self, container, key: str, value) -> None:
        if not any(c is container and k == key for c, k, _ in self._saved_values):
            previous = container.getProperty(key, "value") if container.hasProperty(key, "value") else _MISSING
            self._saved_values.append((container, key, previous))
        container.setProperty(key, "value", value)

    def _restore(self) -> None:
        for container, key, previous in reversed(self._saved_values):
            try:
                if previous is _MISSING:
                    container.removeInstance(key)
                else:
                    container.setProperty(key, "value", previous)
            except Exception:
                Logger.logException("w", "Ultifixer: could not restore %s", key)
        self._saved_values = []

    def _apply(self, nodes, source: Optional[VaseSourceSettings], name: str, why: str, automatic: bool) -> None:
        stack = self._app.getGlobalContainerStack()
        if stack is None:
            return
        plan: VasePlan = make_plan(source, self._nozzleFor(nodes))
        for key, value in plan.global_settings.items():
            self._set(stack.userChanges, key, value)
        for extruder in stack.extruderList:
            for key, value in plan.extruder_settings.items():
                self._set(extruder.userChanges, key, value)
        for node in nodes:
            if node not in self._vase_nodes:
                self._vase_nodes.append(node)
        self._record("applied", file=name, why=why, automatic=automatic,
                     settings=dict(plan.global_settings, **plan.extruder_settings))

        text = ("<b>%s</b> wordt als holle vaas geprint, want %s.<br/>Cura-vaasmodus staat aan (%s)."
                % (name, why, plan.describe()))
        vase_ids = {id(n) for n in self._vase_nodes}
        others = [n for n in self._topLevel(self._sliceableNodes()) if id(n) not in vase_ids]
        if others:
            text += "<br/><b>Let op:</b> er staan ook andere modellen op het bed. Die worden nu ook hol geprint."
        message = self._show(text, "Ultifixer: vaas herkend" if automatic else "Ultifixer: vaasmodus aan",
                             lifetime=30, keep=True)
        message.addAction("undo", "Ongedaan maken", "", "Zet de gewone instellingen terug",
                          button_style=Message.ActionButtonStyle.SECONDARY)
        if automatic:
            message.addAction("never", "Niet meer automatisch", "", "Ultifixer doet dit dan alleen nog via het menu",
                              button_style=Message.ActionButtonStyle.LINK, button_align=Message.ActionButtonAlignment.ALIGN_LEFT)
        message.actionTriggered.connect(self._onMessageAction)
        message.show()

    def _warnIfMixed(self, new_nodes) -> None:
        if self.isActive and new_nodes:
            self._show("Vaasmodus staat aan. Ook dit model wordt dan hol geprint, als één wand. "
                       "Wil je dat niet? Kies Extensies > Ultifixer > Vaasmodus uitzetten.",
                       "Ultifixer: let op", lifetime=20, message_type=Message.MessageType.WARNING)

    def _onMessageAction(self, message, action_id: str) -> None:
        message.hide()
        if action_id == "undo":
            self.undoVaseMode()
        elif action_id == "never":
            if self.autoDetect:
                self.toggleAutoDetect()

    def _show(self, text: str, title: str, lifetime: int = 15, keep: bool = False,
              message_type=Message.MessageType.NEUTRAL) -> Message:
        if self._message is not None:
            self._message.hide()
        message = Message(text, lifetime=lifetime, title=title, message_type=message_type)
        self._message = message
        if not keep:
            message.show()
        return message
