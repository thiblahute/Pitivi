# -*- coding: utf-8 -*-
# Pitivi video editor
#
#       pitivi/timeline/elements.py
#
# Copyright (c) 2013, Mathieu Duponchelle <mduponchelle1@gmail.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA 02110-1301, USA.

"""
Convention throughout this file:
Every GES element which name could be mistaken with a UI element
is prefixed with a little b, example : bTimeline
"""
import os

from gettext import gettext as _

from gi.repository import GES
from gi.repository import Gst
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import GstController
from gi.repository import GObject

from pitivi.utils import ui
from pitivi.utils import misc
from pitivi import configure
from pitivi.timeline import previewers
from pitivi.utils.loggable import Loggable
from pitivi.utils import timeline as timelineUtils

from matplotlib.figure import Figure
from matplotlib.backends.backend_gtk3cairo import FigureCanvasGTK3Cairo as FigureCanvas
import numpy

KEYFRAME_LINE_COLOR = (237, 212, 0)  # "Tango" yellow

CURSORS = {
    GES.Edge.EDGE_START: Gdk.Cursor.new(Gdk.CursorType.LEFT_SIDE),
    GES.Edge.EDGE_END: Gdk.Cursor.new(Gdk.CursorType.RIGHT_SIDE)
}

NORMAL_CURSOR = Gdk.Cursor.new(Gdk.CursorType.LEFT_PTR)
DRAG_CURSOR = Gdk.Cursor.new(Gdk.CursorType.HAND1)


class KeyframeCurve(FigureCanvas, Loggable):

    __gsignals__ = {
        # Signal our values changed, and a redraw will be needed
        "plot-changed": (GObject.SIGNAL_RUN_LAST, None, ()),
        # Signal the keyframes or the curve are being hovered
        "enter": (GObject.SIGNAL_RUN_LAST, None, ()),
        # Signal the keyframes or the curve are not being hovered anymore
        "leave": (GObject.SIGNAL_RUN_LAST, None, ()),
    }

    def __init__(self, timeline, binding, linewidth=1.0):
        figure = Figure()
        FigureCanvas.__init__(self, figure)
        Loggable.__init__(self)

        self.__timeline = timeline
        self._source = binding.props.control_source
        self.__propertyName = binding.props.name
        self.__binding = binding
        self._resetTooltip()

        # Curve values, basically separating source.get_values() timestamps
        # and values.
        self._line_xs = []
        self._line_ys = []

        # axisbg to None for transparency
        self.__ax = figure.add_axes([0, 0, 1, 1], axisbg='None')
        self.__ax.cla()

        # FIXME: drawing a grid and ticks would be nice, but
        # matplotlib is too slow for now.
        self.__ax.grid(False)

        self.__ax.tick_params(axis='both',
                              which='both',
                              bottom='off',
                              top='off',
                              right='off',
                              left='off')

        # This seems to also be necessary for transparency ..
        figure.patch.set_visible(False)

        # The actual Line2D object
        self.__line = None

        # The PathCollection as returned by scatter
        self.__keyframes = None

        sizes = [50]
        colors = ['r']

        self.__keyframes = self.__ax.scatter([], [], marker='D', s=sizes,
                                             c=colors, zorder=2)

        # matplotlib weirdness, simply here to avoid a warning ..
        self.__keyframes.set_picker(True)
        self.__line = self.__ax.plot([], [],
                                     linewidth=linewidth,
                                     zorder=1)[0]
        self._updatePlots()

        # Drag and drop logic
        self.__dragged = False
        self.__offset = None
        self.__handling_motion = False

        self.__hovered = False

        self.connect("motion-notify-event", self.__gtkMotionEventCb)
        self.connect("event", self.__eventCb)

        self.mpl_connect('button_press_event', self.__mplButtonPressEventCb)
        self.mpl_connect(
            'button_release_event', self.__mplButtonReleaseEventCb)
        self.mpl_connect('motion_notify_event', self.__mplMotionEventCb)

        self._connectSources()

    def _connectSources(self):
        self._source.connect("value-added", self._keyframesChangedCb)
        self._source.connect("value-removed", self._keyframesChangedCb)

    def _keyframesChangedCb(self, control_source, kf):
        self._updatePlots()
        self.queue_draw()

    # protected methods
    def _populateLines(self):
        values = self._source.get_all()

        for value in values:
            self._line_xs.append(value.timestamp)
            self._line_ys.append(value.value)

    def _updatePlots(self):
        self._line_xs = []
        self._line_ys = []

        self._populateLines()

        self.__ax.set_xlim(self._line_xs[0], self._line_xs[-1])

        self.__ax.set_ylim(0.0, 1.0)

        arr = numpy.array((self._line_xs, self._line_ys))
        arr = arr.transpose()
        self.__keyframes.set_offsets(arr)
        self.__line.set_xdata(self._line_xs)
        self.__line.set_ydata(self._line_ys)
        self.emit("plot-changed")

    def _createKeyframe(self, timestamp, value):
        self._source.set(timestamp, value)

    def _removeKeyframe(self, timestamp):
        self._source.unset(timestamp)

    def _setTooltip(self, event):
        if event.xdata:
            self.set_tooltip_markup(_("Property: %s\nTimestamp: %s\nValue: %s")
                                    % (self.__propertyName,
                                       Gst.TIME_ARGS(event.xdata),
                                       "{:.3f}".format(event.ydata)))

    def _resetTooltip(self):
        self.set_tooltip_markup(_("Setting property: %s") % str(self.__propertyName))

    def _maybeCreateKeyframe(self, event):
        line_contains = self.__line.contains(event)[0]
        keyframe_existed = self.__keyframes.contains(event)[0]
        if line_contains and not keyframe_existed:
            self._createKeyframe(event.xdata, event.ydata)

    # Callbacks

    def __gtkMotionEventCb(self, widget, event):
        """
        We need to do that here, because mpl's callbacks can't stop
        signal propagation.
        """
        if self.__handling_motion:
            return True
        return False

    def __eventCb(self, element, event):
        if event.type == Gdk.EventType.LEAVE_NOTIFY:
            cursor = NORMAL_CURSOR
            self.__timeline.get_window().set_cursor(cursor)
        return False

    def __mplButtonPressEventCb(self, event):
        result = self.__keyframes.contains(event)
        if result[0]:
            self.__offset = self.__keyframes.get_offsets()[
                result[1]['ind'][0]][0]

            # We won't remove edge keyframes
            is_edge_keyframe = result[1]['ind'][0] == 0 or result[1]['ind'][0] == \
                len(self.__keyframes.get_offsets()) - 1

            if event.guiEvent.type == Gdk.EventType._2BUTTON_PRESS and not \
                    is_edge_keyframe:
                self._removeKeyframe(self.__offset)
            else:
                self.__handling_motion = True

    def __mplMotionEventCb(self, event):
        if not self.props.visible:
            return

        if self.__offset is not None:
            self.__dragged = True
            # Check that the mouse event still is in the figure boundaries
            if event.ydata is not None and event.xdata is not None:
                # The user can not change the timestamp of the first
                # and last keyframes.
                values = self._source.get_all()
                if (values[0].timestamp == self.__offset or
                        values[-1].timestamp == self.__offset):
                    event.xdata = self.__offset

                self._source.unset(int(self.__offset))
                self._createKeyframe(event.xdata, event.ydata)
                self.__offset = event.xdata
                self._setTooltip(event)

        cursor = NORMAL_CURSOR
        result = self.__line.contains(event)
        if result[0]:
            cursor = DRAG_CURSOR
            self._setTooltip(event)
            if not self.__hovered:
                self.emit("enter")
                self.__hovered = True
        elif self.__hovered:
            self.emit("leave")
            self._resetTooltip()
            self.__hovered = False

        self.__timeline.get_window().set_cursor(
            cursor)

    def __mplButtonReleaseEventCb(self, event):
        if not self.__dragged and not self.__offset:
            if event.guiEvent.type == Gdk.EventType.BUTTON_RELEASE:
                self._maybeCreateKeyframe(event)

        self.__offset = None
        self.__handling_motion = False
        self.__dragged = False


class MultiKeyframeCurve(KeyframeCurve):
    def __init__(self, timeline, bindings):
        self.__properties = list(bindings.keys())
        self.__bindings = list(bindings.values())

        super(MultiKeyframeCurve, self).__init__(timeline, self.__bindings[0], linewidth=0.0)

    def _connectSources(self):
        for binding in self.__bindings:
            binding.props.control_source.connect("value-removed", self._keyframesChangedCb)

    def _maybeCreateKeyframe(self, event):
        pass

    def _removeKeyframe(self, timestamp):
        for binding in self.__bindings:
            binding.props.control_source.unset(timestamp)

    def _createKeyframe(self, timestamp, value):
        for binding in self.__bindings:
            binding.props.control_source.set(timestamp, binding.get_value(timestamp))

    def _populateLines(self):
        for binding in self.__bindings:
            values = binding.props.control_source.get_all()
            for value in values:
                self._line_xs.append(value.timestamp)
                self._line_ys.append(0.5)

    def _setTooltip(self, event):
        pass

    def _resetTooltip(self):
        prop_str = ""
        for prop in self.__properties:
            if prop_str:
                prop_str += ", "
            prop_str += prop

        self.set_tooltip_markup(_("Setting properties: %s") % prop_str)


class TimelineElement(Gtk.Layout, timelineUtils.Zoomable, Loggable):
    __gsignals__ = {
        # Signal the keyframes curve are being hovered
        "curve-enter": (GObject.SIGNAL_RUN_LAST, None, ()),
        # Signal the keyframes curve are not being hovered anymore
        "curve-leave": (GObject.SIGNAL_RUN_LAST, None, ()),
    }

    def __init__(self, element, timeline):
        super(TimelineElement, self).__init__()
        timelineUtils.Zoomable.__init__(self)
        Loggable.__init__(self)

        self.set_name(element.get_name())

        self.timeline = timeline
        self._bElement = element
        self._bElement.selected = timelineUtils.Selected()
        self._bElement.selected.connect(
            "selected-changed", self.__selectedChangedCb)

        self.__width = self.__height = 0

        # Needed for effect's keyframe toggling
        self._bElement.ui_element = self

        self.props.vexpand = True

        self.__previewer = self._getPreviewer()
        if self.__previewer:
            self.add(self.__previewer)

        self.__background = self._getBackground()
        if self.__background:
            self.add(self.__background)

        self.__keyframeCurve = None
        self.show_all()

        # We set up the default mixing property right here, if a binding was
        # already set (when loading a project), it will be added later
        # and override that one.
        self.__controlledProperty = self._getDefaultMixingProperty()
        if self.__controlledProperty:
            self.__createControlBinding(self._bElement)

    def release(self):
        if self.__previewer:
            self.__previewer.cleanup()

    # Public API
    def setSize(self, width, height):
        width = max(0, width)
        self.set_size_request(width, height)

        if self.__previewer:
            self.__previewer.set_size_request(width, height)

        if self.__background:
            self.__background.set_size_request(width, height)

        if self.__keyframeCurve:
            self.__keyframeCurve.set_size_request(width, height)

        self.__width = width
        self.__height = height

    def showMultipleKeyframes(self, bindings):
        self.__createKeyframeCurve(list(bindings.values())[0], bindings)

    def showKeyframes(self, effect, prop):
        self.__controlledProperty = prop
        self.__createControlBinding(effect)

    def hideKeyframes(self):
        self.__removeKeyframes()
        self.__controlledProperty = self._getDefaultMixingProperty()
        if self.__controlledProperty:
            self.__createControlBinding(self._bElement)

    def __curveEnterCb(self, unused_keyframe_curve):
        self.emit("curve-enter")

    def __curveLeaveCb(self, unused_keyframe_curve):
        self.emit("curve-leave")

    def __removeKeyframes(self):
        if self.__keyframeCurve:
            try:
                self.__keyframeCurve.disconnect_by_func(self.__keyframePlotChangedCb)
            except TypeError:
                pass

            self.__keyframeCurve.disconnect_by_func(self.__curveEnterCb)
            self.__keyframeCurve.disconnect_by_func(self.__curveLeaveCb)
            self.remove(self.__keyframeCurve)
        self.__keyframeCurve = None

    # Private methods
    def __createKeyframeCurve(self, binding, bindings=[]):
        source = binding.props.control_source
        values = source.get_all()

        if len(values) < 2:
            source.unset_all()
            val = float(self.__controlledProperty.default_value) / \
                (self.__controlledProperty.maximum -
                 self.__controlledProperty.minimum)
            source.set(self._bElement.props.in_point, val)
            source.set(
                self._bElement.props.duration + self._bElement.props.in_point,
                val)

        self.__removeKeyframes()

        if not bindings:
            self.__keyframeCurve = KeyframeCurve(self.timeline, binding)
            self.__keyframeCurve.connect("plot-changed",
                                         self.__keyframePlotChangedCb)
        else:
            self.__keyframeCurve = MultiKeyframeCurve(self.timeline, bindings)

        self.__keyframeCurve.connect("enter", self.__curveEnterCb)
        self.__keyframeCurve.connect("leave", self.__curveLeaveCb)
        self.add(self.__keyframeCurve)
        self.__keyframeCurve.set_size_request(self.__width, self.__height)
        self.__keyframeCurve.props.visible = bool(self._bElement.selected)
        self.queue_draw()

    def __createControlBinding(self, element):
        if self.__controlledProperty:
            element.connect("control-binding-added",
                            self.__controlBindingAddedCb)
            binding = \
                element.get_control_binding(self.__controlledProperty.name)

            if binding:
                self.__createKeyframeCurve(binding)

                return

            source = GstController.InterpolationControlSource()
            source.props.mode = GstController.InterpolationMode.LINEAR
            element.set_control_source(source,
                                       self.__controlledProperty.name, "direct")

    def __controlBindingAddedCb(self, unused_bElement, binding):
        if binding.props.name == self.__controlledProperty.name:
            self.__createKeyframeCurve(binding)

    # Gtk implementation
    def do_set_property(self, property_id, value, pspec):
        Gtk.Layout.do_set_property(self, property_id, value, pspec)

    def do_get_preferred_width(self):
        wanted_width = max(
            0, self.nsToPixel(self._bElement.props.duration) - TrimHandle.SELECTED_WIDTH * 2)

        return wanted_width, wanted_width

    def do_draw(self, cr):
        self.propagate_draw(self.__background, cr)

        if self.__previewer:
            self.propagate_draw(self.__previewer, cr)

        if self.__keyframeCurve and self._bElement.selected and len(self.timeline.selection) == 1:
            self.propagate_draw(self.__keyframeCurve, cr)

    def do_show_all(self):
        for child in self.get_children():
            if bool(self._bElement.selected) or child != self.__keyframeCurve:
                child.show_all()

        self.show()

    # Callbacks
    def __selectedChangedCb(self, unused_bElement, selected):
        if self.__keyframeCurve:
            self.__keyframeCurve.props.visible = selected

        if self.__previewer:
            self.__previewer.setSelected(selected)

    def __keyframePlotChangedCb(self, unused_curve):
        self.queue_draw()

    # Virtual methods
    def _getPreviewer(self):
        """
        Should return a GtkWidget offering a representation of the
        medium (waveforms for audio, thumbnails for video ..).
        This previewer will be automatically scaled to the width and
        height of the TimelineElement.
        """
        return None

    def _getBackground(self):
        """
        Should return a GtkWidget with a unique background color.
        """
        return None

    def _getDefaultMixingProperty(self):
        """
        Should return a controllable GObject.ParamSpec allowing to mix
        media on different layers.
        """
        return None


class TitleSource(TimelineElement):

    __gtype_name__ = "PitiviTitleSource"

    def __init__(self, element, timeline):
        super(TitleSource, self).__init__(element, timeline)
        self.get_style_context().add_class("VideoUriSource")

    def _getBackground(self):
        return VideoBackground()

    def do_get_preferred_height(self):
        return ui.LAYER_HEIGHT / 2, ui.LAYER_HEIGHT


class VideoBackground (Gtk.Box):

    def __init__(self):
        super(VideoBackground, self).__init__(self)
        self.get_style_context().add_class("VideoBackground")


class VideoSource(TimelineElement):

    __gtype_name__ = "PitiviVideoSource"

    def _getBackground(self):
        return VideoBackground()


class VideoUriSource(VideoSource):

    __gtype_name__ = "PitiviUriVideoSource"

    def __init__(self, element, timeline):
        super(VideoUriSource, self).__init__(element, timeline)
        self.get_style_context().add_class("VideoUriSource")

    def _getPreviewer(self):
        previewer = previewers.VideoPreviewer(self._bElement)
        previewer.get_style_context().add_class("VideoUriSource")

        return previewer

    def _getDefaultMixingProperty(self):
        for spec in self._bElement.list_children_properties():
            if spec.name == "alpha":
                return spec


class AudioBackground (Gtk.Box):

    def __init__(self):
        super(AudioBackground, self).__init__(self)
        self.get_style_context().add_class("AudioBackground")


class AudioUriSource(TimelineElement):

    __gtype_name__ = "PitiviAudioUriSource"

    def __init__(self, element, timeline):
        super(AudioUriSource, self).__init__(element, timeline)
        self.get_style_context().add_class("AudioUriSource")

    def _getPreviewer(self):
        previewer = previewers.AudioPreviewer(self._bElement)
        previewer.get_style_context().add_class("AudioUriSource")
        previewer.startLevelsDiscoveryWhenIdle()

        return previewer

    def _getBackground(self):
        return AudioBackground()

    def _getDefaultMixingProperty(self):
        for spec in self._bElement.list_children_properties():
            if spec.name == "volume":
                return spec


class TrimHandle(Gtk.EventBox, Loggable):

    __gtype_name__ = "PitiviTrimHandle"

    SELECTED_WIDTH = 5
    DEFAULT_WIDTH = 1

    def __init__(self, clip, edge):
        Gtk.EventBox.__init__(self)
        Loggable.__init__(self)

        self.clip = clip
        self.get_style_context().add_class("Trimbar")
        self.edge = edge

        self.props.valign = Gtk.Align.FILL
        self.props.width_request = TrimHandle.DEFAULT_WIDTH
        if edge == GES.Edge.EDGE_END:
            self.props.halign = Gtk.Align.END
        else:
            self.props.halign = Gtk.Align.START

        self.connect("notify::window", self._windowSetCb)

    def _windowSetCb(self, window, pspec):
        self.props.window.set_cursor(CURSORS[self.edge])

    def do_draw(self, cr):
        Gtk.EventBox.do_draw(self, cr)
        Gdk.cairo_set_source_pixbuf(cr, GdkPixbuf.Pixbuf.new_from_file(os.path.join(
                                    configure.get_pixmap_dir(), "trimbar-focused.png")), 10, 10)


class Clip(Gtk.EventBox, timelineUtils.Zoomable, Loggable):

    __gtype_name__ = "PitiviClip"

    def __init__(self, layer, bClip):
        super(Clip, self).__init__()
        timelineUtils.Zoomable.__init__(self)
        Loggable.__init__(self)

        self.set_name(bClip.get_name())

        self.handles = []
        self.z_order = -1
        self.layer = layer
        self.timeline = layer.timeline
        self.app = layer.app

        self.bClip = bClip
        self.bClip.ui = self
        self.bClip.selected = timelineUtils.Selected()

        self._audioSource = None
        self._videoSource = None

        self._setupWidget()
        self.__force_position_update = True

        for child in self.bClip.get_children(False):
            self._childAdded(self.bClip, child)
            self.__connectToChild(child)

        self._connectWidgetSignals()

        self._connectGES()
        self.get_accessible().set_name(self.bClip.get_name())

        # To be able to receive effects dragged on clips.
        self.drag_dest_set(0, [ui.EFFECT_TARGET_ENTRY], Gdk.DragAction.COPY)

        self.connect("drag-drop", self.__dragDropCb)

    def __dragDropCb(self, unused_widget, context, x, y, timestamp):
        success = False

        target = self.drag_dest_find_target(context, None)
        if not target:
            return False

        if target.name() == ui.EFFECT_TARGET_ENTRY.target:
            self.info("Adding effect %s", self.timeline.dropData)
            self.app.gui.clipconfig.effect_expander.addEffectToClip(self.bClip,
                                                                    self.timeline.dropData)
            self.timeline.resetSelectionGroup()
            self.timeline.selection.setSelection([self.bClip], timelineUtils.SELECT)
            self.timeline.parent.gui.switchContextTab(self.bClip)
            self.timeline.cleanDropData()
            success = True

        Gtk.drag_finish(context, success, True, timestamp)

        return success

    def __computeHeightAndY(self):
        parent = self.get_parent()
        parent_height = parent.get_allocated_height()

        y = 0
        height = parent_height
        has_video = self.bClip.find_track_elements(None, GES.TrackType.VIDEO, GObject.TYPE_NONE)
        has_audio = self.bClip.find_track_elements(None, GES.TrackType.AUDIO, GObject.TYPE_NONE)
        if not has_video or not has_audio:
            if self.layer and self.layer.media_types == (GES.TrackType.AUDIO | GES.TrackType.VIDEO):
                height = parent_height / 2
                if not has_video:
                    y = height

        return height, y

    def updatePosition(self):
        parent = self.get_parent()

        if not parent or not self.layer:
            return

        start = self.bClip.props.start
        duration = self.bClip.props.duration
        x = self.nsToPixel(start)
        # The calculation of the width assumes that the start is always
        # int(pixels_float). In that case, the rounding can add up and a pixel
        # might be lost if we ignore the start of the clip.
        width = self.nsToPixel(start + duration) - x
        parent_height = parent.get_allocated_height()

        height, y = self.__computeHeightAndY()
        if self.__force_position_update or \
                x != self._current_x or \
                y != self._current_y or \
                width != self._curent_width \
                or parent_height != self._current_parent_height or \
                parent != self._current_parent:

            self.layer.move(self, x, y)
            self.set_size_request(width, height)

            elements = self._elements_container.get_children()
            for child in elements:
                child.setSize(width, height / len(elements))

            self.__force_position_update = False
            self._current_x = x
            self._current_y = y
            self._curent_width = width
            self._current_parent_height = parent.get_allocated_height()
            self._current_parent = parent

    def _setupWidget(self):
        pass

    def sendFakeEvent(self, event, event_widget):
        if event.type == Gdk.EventType.BUTTON_RELEASE:
            self.__buttonReleaseEventCb(event_widget, event)

        self.timeline.sendFakeEvent(event, event_widget)

    def do_draw(self, cr):
        self.updatePosition()
        Gtk.EventBox.do_draw(self, cr)

    def __buttonReleaseEventCb(self, unused_action, unused_actor):
        if self.timeline.got_dragged:
            # This means a drag & drop operation just finished and
            # this button-release-event should be ignored.
            self.timeline.got_dragged = False
            return False

        # TODO : Let's be more specific, masks etc ..
        mode = timelineUtils.SELECT
        if self.timeline.parent._controlMask:
            if not self.get_state_flags() & Gtk.StateFlags.SELECTED:
                mode = timelineUtils.SELECT_ADD
                self.timeline.current_group.add(
                    self.bClip.get_toplevel_parent())
            else:
                self.timeline.current_group.remove(
                    self.bClip.get_toplevel_parent())
                mode = timelineUtils.UNSELECT
        elif not self.get_state_flags() & Gtk.StateFlags.SELECTED:
            self.timeline.resetSelectionGroup()
            self.timeline.current_group.add(
                self.bClip.get_toplevel_parent())
            self.timeline.parent.gui.switchContextTab(self.bClip)
        else:
            self.timeline.resetSelectionGroup()

        parent = self.bClip.get_parent()
        if parent == self.timeline.current_group or parent is None:
            selection = [self.bClip]
        else:
            while parent:
                if parent.get_parent() == self.timeline.current_group:
                    break
                parent = parent.get_parent()

            children = parent.get_children(True)
            selection = [elem for elem in children if isinstance(elem, GES.SourceClip) or
                         isinstance(elem, GES.TransitionClip)]

        self.timeline.selection.setSelection(selection, mode)

        return False

    def _connectWidgetSignals(self):
        self.connect("button-release-event", self.__buttonReleaseEventCb)
        self.connect("event", self._eventCb)

    def release(self):
        for child in self.bClip.get_children(True):
            self.__disconnectFromChild(child)

    def __showHandles(self):
        for handle in self.handles:
            handle.show()

    def __hideHandles(self):
        for handle in self.handles:
            handle.hide()

    def _eventCb(self, element, event):
        if event.type == Gdk.EventType.ENTER_NOTIFY and event.mode == Gdk.CrossingMode.NORMAL:
            ui.set_children_state_recurse(self, Gtk.StateFlags.PRELIGHT)
            for handle in self.handles:
                handle.props.width_request = TrimHandle.SELECTED_WIDTH
        elif event.type == Gdk.EventType.LEAVE_NOTIFY and event.mode == Gdk.CrossingMode.NORMAL:
            ui.unset_children_state_recurse(self, Gtk.StateFlags.PRELIGHT)
            for handle in self.handles:
                handle.props.width_request = TrimHandle.DEFAULT_WIDTH

        return False

    def _startChangedCb(self, unused_clip, unused_pspec):
        self.updatePosition()

    def _durationChangedCb(self, unused_clip, unused_pspec):
        self.updatePosition()

    def _layerChangedCb(self, bClip, unused_pspec):
        self.updatePosition()
        bLayer = bClip.props.layer
        if bLayer:
            self.layer = bLayer.ui

    def __disconnectFromChild(self, child):
        if child.ui:
            if hasattr(child.ui, "__clip_curve_enter_id") and child.ui.__clip_curve_enter_id:
                child.ui.disconnect_by_func(child.ui.__clip_curve_enter_id)
                child.ui.disconnect_by_func(child.ui.__clip_curve_leave_id)
            child.ui.release()

    def __connectToChild(self, child):
        if child.ui:
            child.ui.connect("curve-enter", self.__curveEnterCb)
            child.ui.connect("curve-leave", self.__curveLeaveCb)

    def _childAdded(self, clip, child):
        child.selected = timelineUtils.Selected()
        child.ui = None

    def __curveEnterCb(self, unused_keyframe_curve):
        self.__hideHandles()

    def __curveLeaveCb(self, unused_keyframe_curve):
        self.__showHandles()

    def _childAddedCb(self, clip, child):
        self.__force_position_update = True
        self._childAdded(clip, child)
        self.__connectToChild(child)

    def _childRemoved(self, clip, child):
        pass

    def _childRemovedCb(self, clip, child):
        self.__force_position_update = True
        self.__disconnectFromChild(child)
        self._childRemoved(clip, child)

    def _connectGES(self):
        self.bClip.connect("notify::start", self._startChangedCb)
        self.bClip.connect("notify::inpoint", self._startChangedCb)
        self.bClip.connect("notify::duration", self._durationChangedCb)
        self.bClip.connect("notify::layer", self._layerChangedCb)

        self.bClip.connect_after("child-added", self._childAddedCb)
        self.bClip.connect_after("child-removed", self._childRemovedCb)


class SourceClip(Clip):
    __gtype_name__ = "PitiviSourceClip"

    def __init__(self, layer, bClip):
        super(SourceClip, self).__init__(layer, bClip)

    def _setupWidget(self):
        overlay = Gtk.Overlay()
        self.add(overlay)

        self._elements_container = Gtk.Box.new(Gtk.Orientation.VERTICAL, 2)
        overlay.add_overlay(self._elements_container)

        self.leftHandle = TrimHandle(self, GES.Edge.EDGE_START)
        overlay.add_overlay(self.leftHandle)

        self.rightHandle = TrimHandle(self, GES.Edge.EDGE_END)
        overlay.add_overlay(self.rightHandle)

        self.handles.append(self.leftHandle)
        self.handles.append(self.rightHandle)

        self.get_style_context().add_class("Clip")

    def _childRemoved(self, clip, child):
        if child.ui is not None:
            self._elements_container.remove(child.ui)
            child.ui = None


class UriClip(SourceClip):
    __gtype_name__ = "PitiviuriClip"

    def __init__(self, layer, bClip):
        super(UriClip, self).__init__(layer, bClip)

        self.set_tooltip_markup(misc.filename_from_uri(bClip.get_uri()))
        self.bClip.selected.connect("selected-changed", self._selectedChangedCb)

    def _childAdded(self, clip, child):
        super(UriClip, self)._childAdded(clip, child)

        if isinstance(child, GES.Source):
            if child.get_track_type() == GES.TrackType.AUDIO:
                self._audioSource = AudioUriSource(child, self.timeline)
                child.ui = self._audioSource
                self._elements_container.pack_end(self._audioSource, True, False, 0)
                self._audioSource.set_visible(True)
            elif child.get_track_type() == GES.TrackType.VIDEO:
                self._videoSource = VideoUriSource(child, self.timeline)
                child.ui = self._videoSource
                self._elements_container.pack_start(self._videoSource, True, False, 0)
                self._videoSource.set_visible(True)

    def _selectedChangedCb(self, unused_child, selected):
        self.selected = selected


class TitleClip(SourceClip):
    __gtype_name__ = "PitiviTitleClip"

    def _childAdded(self, clip, child):
        super(TitleClip, self)._childAdded(clip, child)

        if isinstance(child, GES.Source):
            if child.get_track_type() == GES.TrackType.VIDEO:
                self._videoSource = VideoSource(child, self.timeline)
                child.ui = self._videoSource
                self._elements_container.pack_start(self._videoSource, True, False, 0)
                self._videoSource.set_visible(True)


class TransitionClip(Clip):

    __gtype_name__ = "PitiviTransitionClip"

    def __init__(self, layer, bClip):
        self.__has_video = False

        super(TransitionClip, self).__init__(layer, bClip)

        if self.__has_video:
            self.z_order = 1
        else:
            self.z_order = 0
            self.set_sensitive(False)

        self.get_style_context().add_class("TransitionClip")

        self.bClip.connect("child-added", self._childAddedCb)

        # In the case of TransitionClips, we are the only container
        overlay = Gtk.Overlay()
        self.add(overlay)

        self._elements_container = Gtk.Box.new(Gtk.Orientation.VERTICAL, 2)
        overlay.add_overlay(self._elements_container)

        self.leftHandle = TrimHandle(self, GES.Edge.EDGE_START)
        overlay.add_overlay(self.leftHandle)

        self.rightHandle = TrimHandle(self, GES.Edge.EDGE_END)
        overlay.add_overlay(self.rightHandle)

        self.handles.append(self.leftHandle)
        self.handles.append(self.rightHandle)

        self.set_tooltip_markup("%s" % str(bClip.props.vtype.value_nick))

    def do_query_tooltip(self, x, y, keyboard_mode, tooltip):
        if self.__has_video:
            self.set_tooltip_markup("%s" % str(self.bClip.props.vtype.value_nick))
        else:
            self.set_tooltip_markup(_("Audio crossfade"))

        return Clip.do_query_tooltip(self, x, y, keyboard_mode, tooltip)

    def _childAdded(self, clip, child):
        super(TransitionClip, self)._childAdded(clip, child)

        if isinstance(child, GES.VideoTransition):
            self.z_order = 1
            self.set_sensitive(True)
            self.__has_video = True
            child.selected.connect("selected-changed", self._selectedChangedCb, child)

    def do_draw(self, cr):
        Clip.do_draw(self, cr)

    def _selectedChangedCb(self, unused_child, selected, child):
        if selected:
            self.timeline.parent.app.gui.trans_list.activate(child)
            self.selected = True
        else:
            self.selected = False
            self.timeline.parent.app.gui.trans_list.deactivate()


GES_TYPE_UI_TYPE = {
    GES.UriClip.__gtype__: UriClip,
    GES.TitleClip.__gtype__: TitleClip,
    GES.TransitionClip.__gtype__: TransitionClip
}
