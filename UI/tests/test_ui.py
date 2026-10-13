"""Regression tests for fleet selection, retention, filtering and desktop layout."""
import csv
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from sensor_hub import theme
from sensor_hub.mainwindow import MainWindow
from sensor_hub.parser import ParseConfig


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        theme.configure_application(cls.app)

    def setUp(self):
        with patch.object(MainWindow, "_load_config", return_value=ParseConfig()):
            self.window = MainWindow()
        self.window._save_config = lambda config: None
        self.window.ui_timer.stop()
        self.window.setAttribute(Qt.WA_DontShowOnScreen)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def feed(self, board=1, seq=1, value=100, mask="0F", battery=3900):
        self.window.on_line("WB,%d,%d,%d,%s,%d,200,300,400,%d,67" %
                            (board, seq, seq * 1000, mask, value, battery))

    def test_selected_device_stays_selected_and_updates_live(self):
        self.feed(1, value=111)
        self.feed(2, value=222, mask="00")
        self.window._on_board_clicked(1)
        self.feed(2, seq=2, value=999, mask="00")
        self.window._refresh_ui()
        self.assertEqual(self.window.cards["s1"].value_label.text(), "111")
        self.assertEqual(self.window.channel_labels[0].text(), "正常")
        self.feed(1, seq=2, value=333)
        self.window._refresh_ui()
        self.assertEqual(self.window.cards["s1"].value_label.text(), "333")
        self.assertEqual(self.window.board_grid._selected, 1)

    def test_chart_and_battery_history_are_per_device(self):
        self.feed(1, seq=1, value=100, battery=4100)
        self.feed(2, seq=1, value=900, battery=3700)
        self.feed(1, seq=2, value=110, battery=4000)
        self.window._on_board_clicked(2)
        self.assertEqual(list(self.window.chart._data["s1"]), [900])
        self.assertEqual(self.window.battery_history, [(1000, 3700)])
        self.window._on_board_clicked(1)
        self.assertEqual(list(self.window.chart._data["s1"]), [100, 110])
        self.assertEqual(self.window.battery_history, [(1000, 4100), (2000, 4000)])

    def test_battery_history_resets_after_device_reboot(self):
        self.feed(seq=60, battery=3800)
        self.feed(seq=1, battery=3900)
        self.assertEqual(self.window.battery_history, [(1000, 3900)])

    def test_all_frames_in_a_refresh_batch_reach_the_table(self):
        for seq in range(1, 101):
            self.feed(seq=seq)
        self.window._refresh_ui()
        self.assertEqual(self.window.table.rowCount(), 100)
        self.assertEqual(self.window.table.item(0, 2).text(), "1")
        self.assertEqual(self.window.table.item(99, 2).text(), "100")

    def test_retention_keeps_latest_500_table_and_600_chart_frames(self):
        for seq in range(1, 651):
            self.feed(seq=seq)
        self.window._refresh_ui()
        self.assertEqual(self.window.table.rowCount(), 500)
        self.assertEqual(self.window.table.item(0, 2).text(), "151")
        self.assertEqual(len(self.window.chart._data["s1"]), 600)
        self.assertEqual(len(self.window._histories[1]), 600)

    def test_online_expiry_changes_metrics_and_filter_without_new_frames(self):
        self.feed(1)
        self.feed(2)
        self.window.board_grid._boards[2]["ts"] = time.time() - 20
        self.window.online_check.setChecked(True)
        self.window._refresh_ui()
        self.assertEqual(self.window.board_grid.visible_boards(), [1])
        self.assertEqual(self.window.metrics["online"].value_label.text(), "1")
        self.window.board_grid._boards[1]["ts"] = time.time() - 20
        self.window._refresh_ui()
        self.assertEqual(self.window.board_grid.visible_boards(), [])
        self.assertEqual(self.window.metrics["online"].value_label.text(), "0")

    def test_search_and_keyboard_selection(self):
        for board in (1, 12, 13, 42):
            self.feed(board)
        self.window.board_search.setText("1")
        self.assertEqual(self.window.board_grid.visible_boards(), [1, 12, 13])
        self.window._on_board_clicked(12)
        QTest.keyClick(self.window.board_grid, Qt.Key_Right)
        self.assertEqual(self.window._selected_board, 13)
        self.window.board_search.setText("42")
        self.assertEqual(self.window.board_grid.visible_boards(), [42])

    def test_42_devices_are_reachable_at_compact_size(self):
        for board in range(1, 43):
            self.feed(board)
        self.window.resize(1100, 760)
        self.window._refresh_ui()
        self.app.processEvents()
        self.assertGreater(self.window.board_scroll.verticalScrollBar().maximum(), 0)
        self.window._on_board_clicked(42)
        self.app.processEvents()
        self.assertGreater(self.window.board_scroll.verticalScrollBar().value(), 0)
        self.assertIn(42, [board for rect, board in self.window.board_grid._rects])

    def test_clear_resets_every_device_and_readout(self):
        self.feed(1)
        self.feed(2)
        self.window._on_board_clicked(2)
        self.window.clear_data()
        self.assertFalse(self.window._board_cache)
        self.assertFalse(self.window._histories)
        self.assertFalse(self.window._pending_frames)
        self.assertIsNone(self.window._selected_board)
        self.assertEqual(self.window.board_grid.board_count(), 0)
        self.assertEqual(self.window.cards["s1"].value_label.text(), "—")
        self.assertEqual(self.window.batt_pct_card.value_label.text(), "—")
        self.window._on_board_clicked(2)
        self.assertIsNone(self.window._selected_board)

    def test_legacy_frames_use_single_device_and_zero_is_valid(self):
        self.window.on_line("WB,1,1000,0F,0,0,0,0,3900,67")
        self.window._refresh_ui()
        self.assertEqual(self.window._selected_board, 0)
        self.assertEqual(self.window.floor_view._format_total(), "0")
        self.window.floor_view.set_values({})
        self.assertEqual(self.window.floor_view._format_total(), "—")

    def test_typed_serial_port_overrides_previous_item_data(self):
        self.window.port_combo.clear()
        self.window.port_combo.addItem("COM4 — Receiver", "COM4")
        self.window.port_combo.setEditText("COM9")
        self.assertEqual(self.window._selected_port(), "COM9")

    def test_csv_records_every_frame_even_before_ui_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "frames.csv")
            self.window.recorder.open(path)
            for seq in range(1, 31):
                self.feed(seq=seq)
            self.window.recorder.close()
            with open(path, encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(len(list(csv.reader(handle))), 31)

    def test_demo_exercises_all_42_boards_and_restores_controls_on_stop(self):
        self.window.start_receive(demo=True)
        QTest.qWait(400)
        self.assertFalse(self.window.port_combo.isEnabled())
        self.assertTrue(self.window.demo_btn.isChecked())
        self.window._refresh_ui()
        self.assertEqual(self.window.board_grid.board_count(), 42)
        self.window.stop_receive()
        self.assertIsNone(self.window.reader)
        self.assertTrue(self.window.port_combo.isEnabled())
        self.assertFalse(self.window.demo_btn.isChecked())
        self.app.processEvents()
        self.assertEqual(self.window.connection_badge.text(), "●  未连接")


if __name__ == "__main__":
    unittest.main(verbosity=2)
