import sys
import time
import pyautogui
from PIL import Image, ImageGrab
import io
import requests
import base64
import logging
import os
import json
import csv
import sqlite3
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QPushButton, QVBoxLayout, QWidget, QMenu,
                             QHBoxLayout, QFileDialog, QInputDialog, QMessageBox, QSizePolicy, QLayout, QStyle, QDialog, QLineEdit, QListWidget, QScrollArea, QTextEdit)
from PyQt5.QtCore import Qt, QTimer, QPoint, QRect, QThread, QObject, pyqtSignal, pyqtSlot, QSize
from PyQt5.QtGui import QFont, QPainter, QPen, QPixmap, QCursor, QColor
import json
from queue import Queue
import win32gui
import win32ui
import win32con
import win32api
import subprocess

# KoboldCPP server settings
KOBOLDCPP_URL = "http://localhost:5001/api/v1/generate"

logging.basicConfig(filename='app.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')


def resize_image(image):
    """
    Resize the image if it exceeds 1.8 million pixels while maintaining aspect ratio.
    :param image: PIL Image object
    :return: Resized PIL Image object if necessary, otherwise the original image
    """
    MAX_PIXELS = 1_800_000  # 1.8 million pixels
    
    # Calculate current number of pixels
    current_pixels = image.width * image.height
    
    # If the image is already small enough, return it as is
    if current_pixels <= MAX_PIXELS:
        return image
    
    # Calculate the scale factor needed to reduce to 1.8 million pixels
    scale_factor = (MAX_PIXELS / current_pixels) ** 0.5
    
    # Calculate new dimensions, ensuring we round down
    new_width = int(image.width * scale_factor)
    new_height = int(image.height * scale_factor)
    
    # Resize the image using LANCZOS resampling
    return image.resize((new_width, new_height), Image.LANCZOS)


def encode_image_to_base64(image):
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8') 

class HistoryManager:
    def __init__(self, db_path='analysis_history.db'):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS analysis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                analysis_text TEXT,
                prompt TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def add_analysis(self, analysis_text, prompt):
        timestamp = datetime.now().isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO analysis_history (timestamp, analysis_text, prompt) VALUES (?, ?, ?)',
                       (timestamp, analysis_text, prompt))
        conn.commit()
        conn.close()

    def get_history(self, limit=100):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if limit is None:
            cursor.execute('SELECT * FROM analysis_history ORDER BY timestamp DESC')
        else:
            cursor.execute('SELECT * FROM analysis_history ORDER BY timestamp DESC LIMIT ?', (limit,))
        history = cursor.fetchall()
        conn.close()
        return history

    def search_history(self, query):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM analysis_history WHERE analysis_text LIKE ? OR prompt LIKE ? ORDER BY timestamp DESC',
                       (f'%{query}%', f'%{query}%'))
        results = cursor.fetchall()
        conn.close()
        return results

    def export_to_json(self, filename):
        history = self.get_history(limit=None)
        data = [{'id': item[0], 'timestamp': item[1], 'analysis_text': item[2], 'prompt': item[3]} for item in history]
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def export_to_csv(self, filename):
        history = self.get_history(limit=None)
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['ID', 'Timestamp', 'Analysis Text', 'Prompt'])
            writer.writerows(history)

    def get_analysis_by_timestamp(self, timestamp):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM analysis_history WHERE timestamp = ?', (timestamp,))
        analysis = cursor.fetchone()
        conn.close()
        return analysis


class AnalysisWorker(QObject):
    analysis_complete = pyqtSignal(str)
    alert_triggered = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)
    request_screenshot = pyqtSignal()
    screenshot_taken = pyqtSignal()  # Changed to no-argument signal

    def __init__(self):
        super().__init__()
        self.running = True
        self.queue = Queue()
        self.overlay = None

    def set_overlay(self, overlay):
        self.overlay = overlay

    @pyqtSlot()
    def run_analysis(self):
        while self.running:
            try:
                if self.overlay and not self.overlay.is_paused and not self.overlay.analysis_paused:
                    self.request_screenshot.emit()
                    # Wait for the screenshot to be taken
                    timeout = 5  # 5 seconds timeout
                    start_time = time.time()
                    while (not hasattr(self.overlay, 'current_image') or 
                           self.overlay.current_image is None or 
                           self.overlay.current_image.getbbox() is None):
                        if time.time() - start_time > timeout:
                            logging.warning("Timeout waiting for valid screenshot")
                            break
                        time.sleep(0.1)

                    if self.overlay.current_image and self.overlay.current_image.getbbox() is not None:
                        description = analyze_image_with_koboldcpp(self.overlay.current_image, self.overlay.system_prompt)
                        self.analysis_complete.emit(description)
                        
                        if self.overlay.alert_active:
                            self.check_alert_condition(self.overlay.current_image, description)
                    else:
                        logging.warning("Skipping analysis due to invalid screenshot")
                
                # Process any pending UI updates
                while not self.queue.empty():
                    func, args = self.queue.get()
                    func(*args)
            
            except Exception as e:
                self.error_occurred.emit(str(e))
            
            time.sleep(5)


    def check_alert_condition(self, image, analysis_text):
        check_prompt = f"Based on the image and the following analysis, determine if the condition '{self.overlay.alert_prompt}' is met. Respond with only 'Yes' or 'No'.\n\nImage analysis: {analysis_text}"
        
        response = analyze_image_with_koboldcpp(image, check_prompt)
        
        if response.strip().lower() == 'yes':
            self.alert_triggered.emit(self.overlay.alert_prompt, analysis_text)

    def stop(self):
        self.running = False

    def queue_function(self, func, *args):
        self.queue.put((func, args))


def analyze_image_with_koboldcpp(image, prompt):
    if image is None:
        # Use a blank 1x1 pixel image when no image is provided
        blank_image = Image.new('RGB', (1, 1), color='white')
        image_base64 = encode_image_to_base64(blank_image)
    else:
        image_base64 = encode_image_to_base64(image)
    
    payload = {
        "n": 1,
        "max_context_length": 8192,
        "max_length": 100,
        "rep_pen": 1.15,
        "temperature": 0.3,
        "top_p": 1,
        "top_k": 0,
        "top_a": 0,
        "typical": 1,
        "tfs": 1,
        "rep_pen_range": 320,
        "rep_pen_slope": 0.7,
        "sampler_order": [6,0,1,3,4,2,5], #[6, 5, 0, 1, 3, 4, 2],
        "memory": "<|start_header_id|>system<|end_header_id|>\n\n <｜begin_of_sentence｜>{prompt}\n\n",
        "trim_stop": True,
        "images": [image_base64],
        "genkey": "KCPP4535",
        "min_p": 0.1,
        "dynatemp_range": 0,
        "dynatemp_exponent": 1,
        "smoothing_factor": 0,
        "banned_tokens": [],
        "render_special": False,
        "presence_penalty": 0,
        "logit_bias": {},
        "prompt": f"\n(Attached Image)\n<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
        "quiet": True,
        "stop_sequence": ["<|eot_id|><|start_header_id|>user<|end_header_id|>", "<|eot_id|><|start_header_id|>assistant<|end_header_id|>"],
        "use_default_badwordsids": False,
        "bypass_eos": False
    }
    
    try:
        response = requests.post(KOBOLDCPP_URL, json=payload)
        response.raise_for_status()
        result = response.json()
        return result['results'][0]['text'].strip()
    except requests.RequestException as e:
        print(f"Error communicating with KoboldCPP: {e}")
        return "Unable to analyze image at this time."



class TransparentOverlay(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.capture_region = None
        self.is_capturing = False
        self.origin = None
        self.current = None
        self.system_prompt = "describe the image"
        self.is_paused = False
        self.alert_prompt = ""
        self.alert_active = False
        self.current_image = None
        self.analysis_results = []
        self.is_selecting_region = False  # New flag to track region selection state
        self.analysis_paused = False  # New flag to control analysis
        self.start_point = None
        self.end_point = None
        self.buttons_visible = True  # New attribute to track button visibility
        self.hide_during_screenshot = True  # New attribute to control overlay visibility during screenshots
        self.history_manager = HistoryManager()
        self.initUI()


        # Create a directory for saved screenshots
        self.screenshot_dir = "saved_screenshots"
        os.makedirs(self.screenshot_dir, exist_ok=True)

        self.analysis_thread = QThread()
        self.analysis_worker = AnalysisWorker()
        self.analysis_worker.moveToThread(self.analysis_thread)
        self.analysis_thread.started.connect(self.analysis_worker.run_analysis)
        self.analysis_worker.analysis_complete.connect(self.update_text)
        self.analysis_worker.alert_triggered.connect(self.trigger_alert)
        self.analysis_worker.error_occurred.connect(self.handle_error)
        self.analysis_worker.request_screenshot.connect(self.take_screenshot)
        
        self.analysis_worker.set_overlay(self)
        self.analysis_thread.start()



        
    def initUI(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Set a fixed initial size for the overlay
        self.setFixedSize(1500, 800)
        
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        self.label = QLabel(self)
        self.label.setStyleSheet("color: white; background-color: rgba(0, 0, 0, 128); padding: 10px;")
        self.label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.label.setFont(QFont('Arial', 12))
        self.label.setWordWrap(True)
        main_layout.addWidget(self.label)
        
        self.button_widget = QWidget(self)
        self.button_layout = QFlowLayout(self.button_widget)
        self.button_layout.setSpacing(5)
        self.button_layout.setContentsMargins(5, 5, 5, 5)
        
        buttons = [
            ("Select Region", self.select_region),
            ("Update Prompt", self.show_prompt_dialog),
            ("Pause", self.toggle_pause_resume),
            ("Save Results", self.save_results),
            ("Set Alert", self.set_alert_prompt),
            ("Resize Overlay", self.resize_overlay),
            ("Toggle Hide", self.toggle_hide_during_screenshot)  # New button
        ]

        # Add new buttons
        view_history_button = QPushButton("View History", self)
        view_history_button.clicked.connect(self.show_history_dialog)
        self.button_layout.addWidget(view_history_button)
        
        export_button = QPushButton("Export History", self)
        export_button.clicked.connect(self.show_export_dialog)
        self.button_layout.addWidget(export_button)
        
        for text, slot in buttons:
            button = QPushButton(text, self)
            button.clicked.connect(slot)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            if text == "Pause":
                self.pause_resume_button = button  # Store reference to Pause/Resume button
            self.button_layout.addWidget(button)
        
        main_layout.addWidget(self.button_widget)
        
        # Set layout margins and spacing
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        self.show()


    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_buttons_visibility()

    def toggle_buttons_visibility(self):
        self.buttons_visible = not self.buttons_visible
        self.button_widget.setVisible(self.buttons_visible)

    def resize_overlay(self):
        new_width, ok1 = QInputDialog.getInt(self, 'Resize Overlay', 'Enter new width:', self.width(), 100, 2000)
        if ok1:
            new_height, ok2 = QInputDialog.getInt(self, 'Resize Overlay', 'Enter new height:', self.height(), 100, 2000)
            if ok2:
                self.setFixedSize(new_width, new_height)
                self.update_text(f"Overlay resized to {new_width}x{new_height}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.button_widget.setFixedWidth(self.width() - 10)  # Adjust for margins         

    
    def update_text(self, text):
        self.label.setText(text)
        self.analysis_results.append(text)
        # Automatically save the analysis to history
        self.history_manager.add_analysis(text, self.system_prompt)

    def show_history_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Analysis History")
        dialog.setMinimumSize(600, 400)  # Set a minimum size for better usability
        layout = QVBoxLayout(dialog)

        # Add search box
        search_box = QLineEdit(dialog)
        search_box.setPlaceholderText("Search history...")
        layout.addWidget(search_box)

        # Add list widget to display history
        list_widget = QListWidget(dialog)
        layout.addWidget(list_widget)

        # Function to update the list widget
        def update_list(query=''):
            list_widget.clear()
            if query:
                history = self.history_manager.search_history(query)
            else:
                history = self.history_manager.get_history()
            for item in history:
                list_widget.addItem(f"{item[1]}: {item[2][:50]}...")

        # Connect search box to update function
        search_box.textChanged.connect(update_list)

        # Function to open selected analysis
        def open_analysis(item):
            selected_text = item.text()
            parts = selected_text.split(":")  # Split the string into parts
            timestamp = parts[0] + ":" + parts[1] + ":" + parts[2]  # Reconstruct the timestamp
            print(timestamp)
            full_analysis = self.history_manager.get_analysis_by_timestamp(timestamp)
            if full_analysis:
                self.show_analysis_detail(full_analysis)

        # Connect list widget item click to open_analysis function
        list_widget.itemClicked.connect(open_analysis)

        # Initial population of the list
        update_list()

        dialog.exec_()

    def show_analysis_detail(self, analysis):
        detail_dialog = QDialog(self)
        detail_dialog.setWindowTitle(f"Analysis Detail - {analysis[1]}")
        detail_dialog.setMinimumSize(800, 600)  # Set a minimum size for better readability
        layout = QVBoxLayout(detail_dialog)

        # Create a scroll area for the text
        scroll_area = QScrollArea(detail_dialog)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)

        # Create a widget to hold the text
        content_widget = QWidget()
        scroll_area.setWidget(content_widget)
        content_layout = QVBoxLayout(content_widget)

        # Add timestamp
        timestamp_label = QLabel(f"Timestamp: {analysis[1]}")
        timestamp_label.setStyleSheet("font-weight: bold;")
        content_layout.addWidget(timestamp_label)

        # Add prompt
        prompt_label = QLabel(f"Prompt: {analysis[3]}")
        prompt_label.setStyleSheet("font-weight: bold;")
        content_layout.addWidget(prompt_label)

        # Add analysis text
        analysis_text = QTextEdit()
        analysis_text.setPlainText(analysis[2])
        analysis_text.setReadOnly(True)
        content_layout.addWidget(analysis_text)

        detail_dialog.exec_()

    def show_export_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Export History")
        layout = QVBoxLayout(dialog)

        json_button = QPushButton("Export as JSON", dialog)
        csv_button = QPushButton("Export as CSV", dialog)

        layout.addWidget(json_button)
        layout.addWidget(csv_button)

        def export_json():
            filename, _ = QFileDialog.getSaveFileName(self, "Save JSON", "", "JSON Files (*.json)")
            if filename:
                self.history_manager.export_to_json(filename)
                QMessageBox.information(self, "Export Successful", f"Data exported to {filename}")

        def export_csv():
            filename, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)")
            if filename:
                self.history_manager.export_to_csv(filename)
                QMessageBox.information(self, "Export Successful", f"Data exported to {filename}")

        json_button.clicked.connect(export_json)
        csv_button.clicked.connect(export_csv)

        dialog.exec_()
    
    @pyqtSlot(str, str)
    def trigger_alert(self, alert_prompt, analysis_text):
        QTimer.singleShot(0, lambda: self._show_alert(alert_prompt, analysis_text))

    def _show_alert(self, alert_prompt, analysis_text):
        alert = QMessageBox(self)
        alert.setIcon(QMessageBox.Warning)
        alert.setText("Alert Condition Met!")
        alert.setInformativeText(f"The condition '{alert_prompt}' was detected.")
        alert.setDetailedText(analysis_text)
        alert.setWindowTitle("Image Analysis Alert")
        alert.show()

    @pyqtSlot(str)
    def handle_error(self, error_message):
        logging.error(f"Error in analysis thread: {error_message}")
        self.update_text(f"An error occurred: {error_message}")

    def closeEvent(self, event):
        self.analysis_worker.stop()
        self.analysis_thread.quit()
        self.analysis_thread.wait()
        super().closeEvent(event)
    

    def toggle_pause_resume(self):
        self.is_paused = not self.is_paused
        button_text = "Resume" if self.is_paused else "Pause"
        self.pause_resume_button.setText(button_text)  # Update button text
        status = "paused" if self.is_paused else "resumed"
        self.update_text(f"Capture and analysis {status}")
        
        if not self.is_paused:
            self.is_selecting_region = False

    def toggle_hide_during_screenshot(self):
        self.hide_during_screenshot = not self.hide_during_screenshot
        status = "hidden" if self.hide_during_screenshot else "visible"
        self.update_text(f"Overlay will be {status} during screenshots")
    
    def save_results(self):
        if not self.analysis_results:
            self.update_text("No results to save.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Analysis Results", "", "Text Files (*.txt);;All Files (*)")
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as file:
                    for result in self.analysis_results:
                        file.write(result + "\n\n")
                self.update_text(f"Results saved to {file_path}")
            except Exception as e:
                self.update_text(f"Error saving results: {str(e)}")

    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.offset = event.pos()
        elif event.button() == Qt.RightButton:
            self.show_context_menu(event.pos())
    
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.move(self.mapToGlobal(event.pos() - self.offset))
    
    def show_context_menu(self, pos):
        context_menu = QMenu(self)
        hide_buttons = context_menu.addAction("Hide Buttons")
        view_history = context_menu.addAction("View History")
        export_history = context_menu.addAction("Export History")
        update_prompt_action = context_menu.addAction("Update Prompt")
        toggle_pause_action = context_menu.addAction("Pause/Resume")
        save_results_action = context_menu.addAction("Save Results")
        set_alert_action = context_menu.addAction("Set Alert Condition")
        clear_alert_action = context_menu.addAction("Clear Alert")
        resize_action = context_menu.addAction("Resize Overlay")
        toggle_hide = context_menu.addAction("Toggle Hide")
        exit_action = context_menu.addAction("Exit Application")
        
        action = context_menu.exec_(self.mapToGlobal(pos))
        if action == hide_buttons:
            self.toggle_buttons_visibility()
        elif action == update_prompt_action:
            self.show_prompt_dialog()
        elif action == toggle_pause_action:
            self.toggle_pause_resume()
        elif action == view_history:
            self.show_history_dialog()
        elif action == export_history:
            self.show_export_dialog()
        elif action == save_results_action:
            self.save_results()
        elif action == set_alert_action:
            self.set_alert_prompt()
        elif action == clear_alert_action:
            self.clear_alert()
        elif action == resize_action:
            self.resize_overlay()
        elif action == toggle_hide: 
            self.toggle_hide_during_screenshot()
        elif action == exit_action:
            QApplication.quit()
    
    def select_region(self):
        self.is_selecting_region = True
        self.analysis_paused = True
        self.hide()
        self.start_point = None
        self.end_point = None
        QTimer.singleShot(100, self.start_region_selection)
    
    def start_region_selection(self):
        screen = QApplication.primaryScreen()
        self.original_screenshot = screen.grabWindow(0)
        self.select_window = QMainWindow()
        self.select_window.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.select_window.setGeometry(screen.geometry())
        self.select_window.setAttribute(Qt.WA_TranslucentBackground)
        self.select_window.show()
        self.select_window.setMouseTracking(True)
        self.select_window.mousePressEvent = self.region_select_press
        self.select_window.mouseMoveEvent = self.region_select_move
        self.select_window.mouseReleaseEvent = self.region_select_release
        self.select_window.paintEvent = self.region_select_paint



    
    def region_select_press(self, event):
        self.start_point = event.pos()
    
    def region_select_move(self, event):
        if self.start_point:
            self.end_point = event.pos()
            self.select_window.update()
    
    def region_select_release(self, event):
        self.end_point = event.pos()
        if self.start_point and self.end_point:
            self.capture_region = QRect(self.start_point, self.end_point).normalized()
            logging.info(f"Region selected: {self.capture_region}")
            self.update_text(f"Region selected: {self.capture_region}")
        self.is_selecting_region = False
        self.analysis_paused = False
        self.select_window.close()
        self.show()
        self.trigger_analysis()


    def trigger_analysis(self):
        if hasattr(self, 'analysis_worker'):
            self.analysis_worker.request_screenshot.emit() 
    
    def region_select_paint(self, event):
        painter = QPainter(self.select_window)
        painter.drawPixmap(self.select_window.rect(), self.original_screenshot)
        
        if self.start_point and self.end_point:
            painter.setPen(QPen(Qt.red, 2, Qt.SolidLine))
            painter.setBrush(QColor(255, 0, 0, 50))  # Semi-transparent red
            painter.drawRect(QRect(self.start_point, self.end_point).normalized())
        
        # Draw instructions
        painter.setPen(Qt.white)
        painter.setFont(QFont('Arial', 14))
        painter.drawText(10, 30, "Click and drag to select a region. Press Esc to cancel.")

    def update_system_prompt(self, new_prompt):
        self.system_prompt = new_prompt
        print(f"System prompt updated to: {self.system_prompt}")

    
    def show_prompt_dialog(self):
        new_prompt, ok = QInputDialog.getText(self, 'Update System Prompt', 
                                              'Enter new system prompt:',
                                              text=self.system_prompt)
        if ok:
            self.system_prompt = new_prompt
            self.update_text(f"System prompt updated to: {self.system_prompt}")

    def set_alert_prompt(self):
        prompt, ok = QInputDialog.getText(self, 'Set Alert Prompt', 
                                          'Enter alert condition (e.g., "Can you see birds?"):')
        if ok and prompt:
            self.alert_prompt = prompt
            self.alert_active = True
            self.update_text(f"Alert set for condition: {self.alert_prompt}")
        elif ok:
            self.alert_prompt = ""
            self.alert_active = False
            self.update_text("Alert cleared")

    def clear_alert(self):
        self.alert_prompt = ""
        self.alert_active = False
        self.update_text("Alert condition cleared")

    def check_alert_condition(self, image, analysis_text):
        check_prompt = f"Based on the image and the following analysis, determine if the condition '{self.alert_prompt}' is met. Respond with only 'Yes' or 'No'.\n\nImage analysis: {analysis_text}"
        
        response = analyze_image_with_koboldcpp(image, check_prompt)
        
        if response.strip().lower() == 'yes':
            self.trigger_alert(analysis_text)


    @pyqtSlot()
    def take_screenshot(self):
        if self.is_selecting_region:
            logging.info("Region selection in progress, skipping screenshot")
            return
        
        if self.hide_during_screenshot:
            self.hide()  # Hide the overlay only if hide_during_screenshot is True
        QApplication.processEvents()  # Ensure the hide takes effect

        try:
            if self.capture_region and not self.is_selecting_region:
                # Convert QRect to screen coordinates
                screen = QApplication.primaryScreen()
                screen_geometry = screen.geometry()
                left = self.capture_region.left() + screen_geometry.left()
                top = self.capture_region.top() + screen_geometry.top()
                right = self.capture_region.right() + screen_geometry.left()
                bottom = self.capture_region.bottom() + screen_geometry.top()

                # Use win32 API for screen capture
                hwin = win32gui.GetDesktopWindow()
                width = right - left
                height = bottom - top

                hwindc = win32gui.GetWindowDC(hwin)
                srcdc = win32ui.CreateDCFromHandle(hwindc)
                memdc = srcdc.CreateCompatibleDC()
                bmp = win32ui.CreateBitmap()
                bmp.CreateCompatibleBitmap(srcdc, width, height)
                memdc.SelectObject(bmp)
                memdc.BitBlt((0, 0), (width, height), srcdc, (left, top), win32con.SRCCOPY)

                signedIntsArray = bmp.GetBitmapBits(True)
                img = Image.frombytes("RGB", (width, height), signedIntsArray, "raw", "BGRX")

                # Free resources
                win32gui.DeleteObject(bmp.GetHandle())
                memdc.DeleteDC()
                srcdc.DeleteDC()
                win32gui.ReleaseDC(hwin, hwindc)

                logging.info(f"Screenshot taken of selected region: {left},{top},{right},{bottom}")
            else:
                img = ImageGrab.grab()
                logging.info("Full screen screenshot taken")

            if self.hide_during_screenshot:
                self.show()  # Show the overlay immediately after taking the screenshot

            # Save the full-size screenshot
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
            filepath = os.path.join(self.screenshot_dir, filename)
            img.save(filepath)
            logging.info(f"Screenshot saved: {filepath}")  
            
            self.current_image = resize_image(img)
            
            if self.current_image.getbbox() is None:
                logging.warning("Captured image is empty")
            else:
                logging.info(f"Captured image size: {self.current_image.size}")

        except Exception as e:
            logging.error(f"Error taking screenshot: {str(e)}")
            self.current_image = None
        finally:
            if self.hide_during_screenshot:
                self.show()  # Show the overlay again only if it was hidden
            self.analysis_worker.screenshot_taken.emit()

class QFlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1):
        super(QFlowLayout, self).__init__(parent)
        self.itemList = []
        self.m_hSpace = spacing
        self.m_vSpace = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self.itemList.append(item)

    def horizontalSpacing(self):
        if self.m_hSpace >= 0:
            return self.m_hSpace
        else:
            return self.smartSpacing(QStyle.PM_LayoutHorizontalSpacing)

    def verticalSpacing(self):
        if self.m_vSpace >= 0:
            return self.m_vSpace
        else:
            return self.smartSpacing(QStyle.PM_LayoutVerticalSpacing)

    def count(self):
        return len(self.itemList)

    def itemAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        height = self.doLayout(QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect):
        super(QFlowLayout, self).setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

    def doLayout(self, rect, testOnly):
        x = rect.x()
        y = rect.y()
        lineHeight = 0

        for item in self.itemList:
            wid = item.widget()
            spaceX = self.horizontalSpacing()
            if spaceX == -1:
                spaceX = wid.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal)
            spaceY = self.verticalSpacing()
            if spaceY == -1:
                spaceY = wid.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical)
            
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0

            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())

        return y + lineHeight - rect.y()

    def smartSpacing(self, pm):
        parent = self.parent()
        if not parent:
            return -1
        elif parent.isWidgetType():
            return parent.style().pixelMetric(pm, None, parent)
        else:
            return parent.spacing()
        
    
           


def capture_and_analyze(overlay):
    while True:
        if not overlay.is_paused:
            if overlay.capture_region and not overlay.is_capturing:
                screenshot = pyautogui.screenshot(region=(
                    overlay.capture_region.x(),
                    overlay.capture_region.y(),
                    overlay.capture_region.width(),
                    overlay.capture_region.height()
                ))
            else:
                screenshot = pyautogui.screenshot()
            
            resized_image = resize_image(screenshot)
            overlay.current_image = resized_image  # Store the current image
            
            description = analyze_image_with_koboldcpp(resized_image, overlay.system_prompt)
            overlay.update_text(description)
        time.sleep(5)


def main():
    app = QApplication(sys.argv)
    overlay = TransparentOverlay()
    overlay.show()

    # Ensure the analysis worker is properly connected
    overlay.analysis_worker.set_overlay(overlay)
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main() 


