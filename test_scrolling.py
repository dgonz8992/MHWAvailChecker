"""Scroll input/routing tests independent of an available desktop display."""
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import MagicMock, patch

from main import AvailabilityApp


class ScrollingTests(unittest.TestCase):
    def wheel_app(self, system='aqua'):
        widget = object()
        app = SimpleNamespace(_wheel_remainders={},
                              tk=SimpleNamespace(call=lambda *args: system),
                              winfo_containing=lambda x, y: widget,
                              _scroll_in_direction=MagicMock())
        return app, widget

    def event(self, delta=0, num='??', state=0):
        return SimpleNamespace(delta=delta, num=num, state=state, x_root=10, y_root=10, widget=None)

    def test_tk9_mouse_wheel_tick_is_three_rows_not_120(self):
        app, widget = self.wheel_app()
        with patch('main.tk.TkVersion', 9.0):
            AvailabilityApp._scroll_wheel(app, self.event(delta=-120))
        app._scroll_in_direction.assert_called_once_with(widget, 'y', 3)

    def test_windows_partial_wheel_ticks_accumulate(self):
        app, widget = self.wheel_app('win32')
        AvailabilityApp._scroll_wheel(app, self.event(delta=-60))
        app._scroll_in_direction.assert_not_called()
        AvailabilityApp._scroll_wheel(app, self.event(delta=-60))
        app._scroll_in_direction.assert_called_once_with(widget, 'y', 1)

    def test_linux_wheel_buttons_and_shift_axis(self):
        app, widget = self.wheel_app('x11')
        AvailabilityApp._scroll_wheel(app, self.event(num=4))
        app._scroll_in_direction.assert_called_with(widget, 'y', -1)
        AvailabilityApp._scroll_wheel(app, self.event(num=5, state=1))
        app._scroll_in_direction.assert_called_with(widget, 'x', 1)

    def test_tk9_packed_trackpad_deltas_support_both_axes(self):
        app, widget = self.wheel_app()
        packed = (-40 << 16) | (-60 & 0xffff)
        AvailabilityApp._scroll_touchpad(app, self.event(delta=packed))
        self.assertEqual(app._scroll_in_direction.call_args_list[0].args, (widget, 'x', 2))
        self.assertEqual(app._scroll_in_direction.call_args_list[1].args, (widget, 'y', 3))

    def test_small_trackpad_movements_are_preserved(self):
        app, widget = self.wheel_app()
        for _ in range(9):
            AvailabilityApp._scroll_touchpad(app, self.event(delta=(-2 & 0xffff)))
        app._scroll_in_direction.assert_not_called()
        # Floating point remainder can be just below one, so exercise another
        # event too; no movement is discarded between precise events.
        for _ in range(2):
            AvailabilityApp._scroll_touchpad(app, self.event(delta=(-2 & 0xffff)))
        app._scroll_in_direction.assert_called_once_with(widget, 'y', 1)

    def test_scroll_continues_from_field_at_edge_to_containing_canvas(self):
        canvas = MagicMock(spec=tk.Canvas)
        canvas.yview.return_value = (0, .5)
        canvas.master = None
        field = MagicMock(spec=tk.Text)
        field.yview.return_value = (0, 1)
        field.master = canvas
        AvailabilityApp._scroll_in_direction(SimpleNamespace(table=None), field, 'y', 1)
        field.yview_scroll.assert_not_called()
        canvas.yview_scroll.assert_called_once_with(1, 'units')

    def test_scrolling_over_scrollbar_uses_its_paired_widget(self):
        canvas = MagicMock(spec=tk.Canvas)
        canvas.yview.return_value = (0, .5)
        canvas.master = None
        scrollbar = MagicMock(spec=ttk.Scrollbar)
        scrollbar.master = SimpleNamespace(winfo_children=lambda: [canvas, scrollbar])
        AvailabilityApp._scroll_in_direction(SimpleNamespace(table=None), scrollbar, 'y', 1)
        canvas.yview_scroll.assert_called_once_with(1, 'units')

    def test_schedule_scroll_commits_active_booking_before_moving(self):
        table = MagicMock(spec=ttk.Treeview)
        table.yview.return_value = (0, .5)
        table.master = None
        app = SimpleNamespace(table=table, _finish_schedule_edit=MagicMock())
        events = []
        app._finish_schedule_edit.side_effect = lambda: events.append('commit')
        table.yview_scroll.side_effect = lambda *args: events.append('scroll')
        AvailabilityApp._scroll_in_direction(app, table, 'y', 1)
        self.assertEqual(events, ['commit', 'scroll'])


if __name__ == '__main__':
    unittest.main()
