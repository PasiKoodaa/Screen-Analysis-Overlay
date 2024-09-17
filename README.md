# Screen Analysis Overlay

This application provides a transparent overlay for real-time image analysis using KoboldCPP. It captures screenshots of a selected region or the entire screen and analyzes them using AI, providing descriptions and alerts based on user-defined conditions.






https://github.com/user-attachments/assets/53d47ec5-704a-4ff2-a21c-796f739a1c5e







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
- Toggle overlay visibility during screenshots
- Saves analysis history to SQL database
> Search and view analysis history
> Export analysis history to JSON or CSV file

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
   On Windows, use `venv\Scripts\activate`
   pip install -r requirements.txt
   ```

3. Ensure you have KoboldCPP running locally on `http://localhost:5001`. Adjust the `KOBOLDCPP_URL` in the script if your setup is different.

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

4. The overlay will continuously capture and analyze the selected region, displaying results in real-time.

## Configuration
![kobo](https://github.com/user-attachments/assets/c8781ff4-b7c5-47a4-b72e-84da4a5e3ea2)

- Adjust the `KOBOLDCPP_URL` variable in the script if your KoboldCPP server is running on a different address.
- Modify the `system_prompt` variable to change the default analysis prompt.



