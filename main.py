import sys
import time
import pyautogui
from PIL import Image, ImageGrab
import io
import requests
import base64
import logging
import os
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QPushButton, QVBoxLayout, QWidget, QMenu,
                             QHBoxLayout, QFileDialog, QInputDialog, QMessageBox, QSizePolicy, QLayout, QStyle)
from PyQt5.QtCore import Qt, QTimer, QPoint, QRect, QThread, QObject, pyqtSignal, pyqtSlot, QSize
from PyQt5.QtGui import QFont, QPainter, QPen, QPixmap, QCursor, QColor
import json
from queue import Queue
import win32gui
import win32ui
import win32con
import win32api

# KoboldCPP server settings
KOBOLDCPP_URL = "http://localhost:5001/api/v1/generate"

logging.basicConfig(filename='app.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')


def resize_image(image, scale_factor=0.5):
    """
    Resize the image by a given scale factor.
    :param image: PIL Image object
    :param scale_factor: Factor to scale the image by (e.g., 0.5 for half size)
    :return: Resized PIL Image object
    """
    new_size = (int(image.width * scale_factor), int(image.height * scale_factor))
    return image.resize(new_size, Image.LANCZOS)


def encode_image_to_base64(image):
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8') 




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
        self.setFixedSize(1150, 800)
        
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
        hide_action = context_menu.addAction("Hide Overlay")
        update_prompt_action = context_menu.addAction("Update Prompt")
        toggle_pause_action = context_menu.addAction("Pause/Resume")
        save_results_action = context_menu.addAction("Save Results")
        set_alert_action = context_menu.addAction("Set Alert Condition")
        clear_alert_action = context_menu.addAction("Clear Alert")
        resize_action = context_menu.addAction("Resize Overlay")  # Add this line
        exit_action = context_menu.addAction("Exit Application")
        
        action = context_menu.exec_(self.mapToGlobal(pos))
        if action == hide_action:
            self.hide()
        elif action == update_prompt_action:
            self.show_prompt_dialog()
        elif action == toggle_pause_action:
            self.toggle_pause_resume()
        elif action == save_results_action:
            self.save_results()
        elif action == set_alert_action:
            self.set_alert_prompt()
        elif action == clear_alert_action:
            self.clear_alert()
        elif action == resize_action:  # Add this block
            self.resize_overlay()
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
                                          'Enter alert condition (e.g., "Alert when you see a robbery"):')
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
            
            self.current_image = resize_image(img, scale_factor=0.25)
            
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
            
            resized_image = resize_image(screenshot, scale_factor=0.25)
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

