# Screen Analysis Overlay

This application provides a transparent overlay for real-time image analysis using KoboldCPP or Ollama. It captures screenshots of a selected region or the entire screen and analyzes them using AI, providing descriptions and alerts based on user-defined conditions. Currently only Windows compatible.






https://github.com/user-attachments/assets/53d47ec5-704a-4ff2-a21c-796f739a1c5e





https://github.com/user-attachments/assets/240f12f5-2197-4cf4-88d1-ba273b509393





## Features

- Transparent overlay that stays on top of other windows
- Customizable capture region selection
- Real-time screen analysis using KoboldCPP or Ollama
- Customizable system prompts for analysis
- Pause/Resume functionality
- Alert system for specific conditions
- Ability to save analysis results
- Resizable overlay
- Hide/show buttons by double clicking the overlay
- Toggle overlay visibility during screenshots
- Saves analysis history to SQL database
- Search and view analysis history
- Export analysis history to JSON or CSV file
- Set analysis Start and End times
- Switch between KoboldCPP and Ollama backends
- Choose Ollama model for analysis

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
   git clone https://github.com/PasiKoodaa/Screen-Analysis-Overlay
   cd image-analysis-overlay
   ```


2. Set up a Python environment:

   ### Option 1: Using Conda

   ```
   conda create -n screen-analysis python=3.9
   conda activate screen-analysis
   pip install -r requirements.txt
   ```

   ### Option 2: Using venv and pip

   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Ensure you have KoboldCPP running locally on `http://localhost:5001` or Ollama running on `http://localhost:11434`. Adjust the `KOBOLDCPP_URL` in the script if your setup is different.

## Usage

1. Run the application:
   ```
   python main.py
   ```

2. Use the buttons or right-click context menu to:
   - View history and search history
   - Export history to JSON or CSV
   - Select a capture region
   - Update the analysis prompt
   - Pause/Resume analysis
   - Set alert conditions
   - Save analysis results
   - Resize the overlay
   - Toggle overlay visibility during screenshots
   - Select backend (KoboldCPP or Ollama)
   - Choose Ollama model (when using Ollama backend)

4. The overlay will continuously capture and analyze the selected region, displaying results in real-time.

## Configuration
![kobo](https://github.com/user-attachments/assets/c8781ff4-b7c5-47a4-b72e-84da4a5e3ea2)

- Adjust the `KOBOLDCPP_URL` variable in the script if your KoboldCPP server is running on a different address.
- Modify the `system_prompt` variable to change the default analysis prompt.

## Using Ollama Backend

1. Ensure Ollama is installed and running on your system.
2. In the application, click "Select Backend" button.
3. Choose "Ollama" as the backend.
4. Enter the desired Ollama model name (e.g., "llava" or "minicpm-v").
5. Click "OK" to confirm the selection.


