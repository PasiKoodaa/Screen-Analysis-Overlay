# Screen Analysis Overlay

This application provides a transparent overlay for real-time image analysis using KoboldCPP. It captures screenshots of a selected region or the entire screen and analyzes them using AI, providing descriptions and alerts based on user-defined conditions.





https://github.com/user-attachments/assets/033eb996-5ead-43f1-a736-633808dc284f





## Features

- Transparent overlay that stays on top of other windows
- Customizable capture region selection
- Real-time screen analysis using KoboldCPP
- Customizable system prompts for analysis
- Pause/Resume functionality
- Alert system for specific conditions
- Ability to save analysis results
- Resizable overlay
- Hide/show buttons by double clicking the overlay

## Requirements

- Python 3.8+
- PyQt5
- pyautogui
- Pillow
- requests
- pywin32

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/image-analysis-overlay.git
   cd image-analysis-overlay
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Ensure you have KoboldCPP running locally on `http://localhost:5001`. Adjust the `KOBOLDCPP_URL` in the script if your setup is different.

## Usage

1. Run the application:
   ```
   python main.py
   ```

2. Use the buttons or right-click context menu to:
   - Select a capture region
   - Update the analysis prompt
   - Pause/Resume analysis
   - Set alert conditions
   - Save analysis results
   - Resize the overlay

3. The overlay will continuously capture and analyze the selected region, displaying results in real-time.

## Configuration
![kobo](https://github.com/user-attachments/assets/c8781ff4-b7c5-47a4-b72e-84da4a5e3ea2)

- Adjust the `KOBOLDCPP_URL` variable in the script if your KoboldCPP server is running on a different address.
- Modify the `system_prompt` variable to change the default analysis prompt.



