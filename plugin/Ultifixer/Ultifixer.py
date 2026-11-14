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

from .project_settings import VaseSourceSettings, read_3mf_settings, read_negative_parts
from .vase_settings import VasePlan, _nl, make_plan, part_settings
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
        self._saved_parts: List[Tuple[object, str, object]] = []  # per-object settings of Bambu parts
        self._hole_nodes: List[object] = []  # cutting meshes this plugin added
        self._size_note = ""
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
                self._size_note = ""
                holes = self._applyParts(new_nodes, source, os.path.basename(file_name))
                if source.has_negative_parts and not holes:
                    try:
                        holes = self._addHoles(new_nodes, source, file_name)
                    except Exception:  # never let a weird file break Cura
                        Logger.logException("w", "Ultifixer: could not add the holes of %s", file_name)
                self._keepOnPlate(new_nodes, os.path.basename(file_name))
                if source.spiral_mode:
                    self._apply(new_nodes, source, os.path.basename(file_name),
                                "het bestand zegt: vaasmodus (%s)" % ("Bambu Studio" if source.slicer == "bambu" else "PrusaSlicer"),
                                automatic=True)
                else:
                    self._record("not_vase", file=os.path.basename(file_name), reason="3MF has vase mode off")
                    if holes:
                        self._showHoles(os.path.basename(file_name))
                    else:
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

    @staticmethod
    def _putBack(saved) -> None:
        for container, key, previous in reversed(saved):
            try:
                if previous is _MISSING:
                    container.removeInstance(key)
                else:
                    container.setProperty(key, "value", previous)
            except Exception:
                Logger.logException("w", "Ultifixer: could not restore %s", key)

    def _restore(self) -> None:
        self._putBack(self._saved_values)
        self._saved_values = []

    # ------------------------------------------------- Bambu parts (holes)

    def _applyParts(self, new_nodes, source: VaseSourceSettings, name: str) -> int:
        """Give the parts of a Bambu object their meaning in Cura. Returns the number of holes made.

        Cura loads a Bambu object with several parts as a group, one child per part in file
        order, and prints every child as plastic. A "negative part" then fills the hole it
        was meant to cut.
        """
        if not source.parts:
            return 0
        groups = []
        for node in new_nodes:
            parent = node.getParent()
            if parent is not None and parent.callDecoration("isGroup") and all(parent is not g for g in groups):
                groups.append(parent)
        holes = 0
        for object_id, kinds in source.parts.items():
            matches = [g for g in groups if str(g.getId()) == object_id and len(g.getChildren()) == len(kinds)]
            if not matches and len(source.parts) == 1:
                matches = [g for g in groups if len(g.getChildren()) == len(kinds)]
            if len(matches) != 1:
                continue  # the usual case: Cura left the special parts out, see _addHoles
            for child, kind in zip(matches[0].getChildren(), kinds):
                settings = part_settings(kind)
                if settings is None:
                    continue
                try:
                    self._setOnNode(child, settings)
                except Exception:
                    Logger.logException("w", "Ultifixer: could not set up part %s of %s", kind, name)
                    continue
                holes += kind == "negative_part"
            self._record("parts", file=name, object=object_id, kinds=kinds)
        return holes

    def _addHoles(self, new_nodes, source: VaseSourceSettings, file_name: str) -> int:
        """Add the negative parts that Cura's 3MF reader left out, as meshes that cut a hole.

        Cura loads only the printed parts of a Bambu object, as one mesh. A negative part gets
        the same coordinates and the same place in the scene, and is then grouped with the
        model so that the two move together.
        """
        from UM.Math.Matrix import Matrix
        from UM.Mesh.MeshBuilder import MeshBuilder
        from UM.Operations.GroupedOperation import GroupedOperation
        from cura.Operations.SetParentOperation import SetParentOperation
        from UM.Scene.GroupDecorator import GroupDecorator
        from cura.Scene.BuildPlateDecorator import BuildPlateDecorator
        from cura.Scene.ConvexHullDecorator import ConvexHullDecorator
        from cura.Scene.CuraSceneNode import CuraSceneNode
        from cura.Scene.SliceableObjectDecorator import SliceableObjectDecorator

        name = os.path.basename(file_name)
        found = read_negative_parts(file_name, source)
        made = 0
        for object_id, parts in found.items():
            models = [n for n in new_nodes if str(n.getId()) == object_id and n.getMeshData() is not None]
            if not models and len(found) == 1 and len(new_nodes) == 1 and new_nodes[0].getMeshData() is not None:
                models = list(new_nodes)
            if len(models) != 1:
                self._record("parts_skipped", file=name, object=object_id, reason="model not found in Cura")
                continue
            model = models[0]

            # Cura moved the mesh so that its middle is at zero. The same triangle in the file
            # and in Cura tells how far; all three corners must agree, or the meshes differ.
            mesh = model.getMeshData()
            cura_corners = numpy.asarray(mesh.getVertices(), dtype=numpy.float64)
            cura_corners = cura_corners[numpy.asarray(mesh.getIndices())[0]] if mesh.getIndices() is not None else cura_corners[:3]
            rotation, offset = parts.anchor_matrix[:3], parts.anchor_matrix[3]
            to_local = None
            for baked in (False, True):  # did Cura put the part's own transform into the mesh?
                anchor = parts.anchor @ rotation + offset if baked else parts.anchor
                shift = anchor - cura_corners
                if numpy.abs(shift - shift[0]).max() < 0.01:
                    if baked:
                        to_local = lambda points, shift=shift: points - shift[0]
                    else:
                        inverse = numpy.linalg.inv(rotation)
                        to_local = lambda points, shift=shift, inverse=inverse: (points - offset) @ inverse - shift[0]
                    break
            if to_local is None:
                self._record("parts_skipped", file=name, object=object_id, reason="mesh in Cura differs from the file")
                continue

            build_plate = model.callDecoration("getBuildPlateNumber") or 0
            holes = []
            for triangles in parts.holes:
                builder = MeshBuilder()
                builder.setVertices(numpy.asarray(to_local(triangles.reshape(-1, 3)), dtype=numpy.float32))
                builder.calculateNormals(fast=True)
                hole = CuraSceneNode()
                hole.setName("Uitsparing")
                hole.setMeshData(builder.build())
                hole.setSelectable(True)
                hole.addDecorator(BuildPlateDecorator(build_plate))
                hole.addDecorator(ConvexHullDecorator())
                hole.addDecorator(SliceableObjectDecorator())
                hole.setTransformation(Matrix(model.getWorldTransformation(copy=True).getData()))
                hole.setParent(model.getParent())
                saved = len(self._saved_parts)
                self._setOnNode(hole, part_settings("negative_part"))
                del self._saved_parts[saved:]  # undo removes the whole node instead
                holes.append(hole)

            # Group the model with its holes, as Cura's own "Group models" does.
            group = CuraSceneNode()
            group.setName(model.getName())
            group.addDecorator(GroupDecorator())
            group.addDecorator(ConvexHullDecorator())
            group.addDecorator(BuildPlateDecorator(build_plate))
            group.setParent(model.getParent())
            group.setSelectable(True)
            center = model.getWorldPosition()
            group.setPosition(center)
            group.setCenterPosition(center)
            operation = GroupedOperation()
            for node in [model] + holes:
                operation.addOperation(SetParentOperation(node, group))
            operation.push()

            self._hole_nodes.extend(holes)
            made += len(holes)
            factor, resized = self._restoreSize(group, model, rotation)
            self._record("holes", file=name, object=object_id, count=len(holes), scale=factor, resized=resized)
            if factor != 1.0:
                self._size_note = ("Het model staat nu ook op de bedoelde grootte (%s× zo groot als Cura het opende)."
                                   if resized else
                                   "Let op: het model is %s× zo klein als bedoeld; op ware grootte past het niet op deze printer."
                                   ) % _nl(factor)
        return made

    def _keepOnPlate(self, new_nodes, name: str) -> None:
        """Move a model that hangs over the edge of the plate to the middle.

        A 3MF from another slicer keeps its place on that printer's plate. On a smaller plate
        Cura (up to 5.13) then puts a large model partly outside, and refuses to slice it.
        """
        from UM.Math.Vector import Vector
        from UM.Scene.SceneNode import SceneNode
        stack = self._app.getGlobalContainerStack()
        tops = []
        for node in new_nodes:
            parent = node.getParent()
            top = parent if parent is not None and parent.callDecoration("isGroup") else node
            if all(top is not t for t in tops):
                tops.append(top)
        if stack is None or len(tops) != 1:
            return
        box = tops[0].getBoundingBox()
        if box is None:
            return
        width = float(stack.getProperty("machine_width", "value"))
        depth = float(stack.getProperty("machine_depth", "value"))
        outside = box.left < -width / 2 or box.right > width / 2 or box.back < -depth / 2 or box.front > depth / 2
        if not outside or box.width > width or box.depth > depth:
            return
        tops[0].translate(Vector(-box.center.x, 0, -box.center.z), SceneNode.TransformSpace.World)
        self._record("centered", file=name)

    def _restoreSize(self, group, model, rotation) -> Tuple[float, bool]:
        """Bambu Studio stores a scale per part, which Cura ignores: the model opens too small or too big.

        Returns (factor, applied). Only a plain, equal scale in all directions is put back, and
        only when the model then still fits the printer.
        """
        from UM.Math.Vector import Vector
        from UM.Scene.SceneNode import SceneNode
        factor = float(rotation[0, 0])
        if factor <= 0 or abs(factor - 1.0) < 1e-3 or numpy.abs(rotation - numpy.eye(3) * factor).max() > 1e-4 * factor:
            return 1.0, False
        factor = round(factor, 4)
        box = model.getBoundingBox()
        stack = self._app.getGlobalContainerStack()
        if box is None or stack is None:
            return factor, False
        room = [float(stack.getProperty(key, "value")) for key in ("machine_width", "machine_height", "machine_depth")]
        if any(size * factor > limit - 0.5 for size, limit in zip((box.width, box.height, box.depth), room)):
            return factor, False
        group.scale(Vector(factor, factor, factor), SceneNode.TransformSpace.Local)
        box = model.getBoundingBox()
        if box is not None:
            # Back onto the plate; and to the middle when it now sticks out over the edge.
            # (Cura's scene always has the middle of the plate at zero.)
            outside = (box.left < -room[0] / 2 or box.right > room[0] / 2
                       or box.back < -room[2] / 2 or box.front > room[2] / 2)
            move = Vector(-box.center.x if outside else 0, -box.bottom, -box.center.z if outside else 0)
            group.translate(move, SceneNode.TransformSpace.World)
        return factor, True

    def _setOnNode(self, node, settings: Dict[str, object]) -> None:
        from UM.Settings.SettingInstance import SettingInstance
        stack = node.callDecoration("getStack")
        if stack is None:
            from cura.Settings.SettingOverrideDecorator import SettingOverrideDecorator
            node.addDecorator(SettingOverrideDecorator())
            stack = node.callDecoration("getStack")
        container = stack.getTop()
        for key, value in settings.items():
            instance = container.getInstance(key)
            self._saved_parts.append((container, key, _MISSING if instance is None else instance.value))
            if instance is None:
                instance = SettingInstance(stack.getSettingDefinition(key), container)
                instance.setProperty("value", value)
                instance.resetState()
                container.addInstance(instance)
            else:
                container.setProperty(key, "value", value)

    def _showHoles(self, name: str) -> None:
        message = self._show("<b>%s</b> heeft een uitsparing die Bambu Studio wegsnijdt. Cura zou die dichtprinten; "
                             "Ultifixer laat Cura er nu ook een gat van maken.%s"
                             % (name, "<br/>" + self._size_note if self._size_note else ""),
                             "Ultifixer: uitsparing herkend", lifetime=30, keep=True)
        message.addAction("undo_parts", "Ongedaan maken", "", "Print de uitsparing weer als gewoon onderdeel",
                          button_style=Message.ActionButtonStyle.SECONDARY)
        message.actionTriggered.connect(self._onMessageAction)
        message.show()

    def undoParts(self) -> None:
        self._putBack(self._saved_parts)
        self._saved_parts = []
        for hole in self._hole_nodes:
            if hole.getParent() is not None:
                hole.setParent(None)
        self._hole_nodes = []
        self._record("parts_restored", reason="user")

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
        elif action_id == "undo_parts":
            self.undoParts()
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
