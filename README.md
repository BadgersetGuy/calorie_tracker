# Calorie Tracker App

A mobile-first web application for tracking calories and macronutrients using AI-powered image recognition.

## Features

- Take photos of meals using your mobile device's camera
- AI-powered food recognition and nutritional analysis
- Track weight of meals in grams
- View daily macro and calorie totals
- Historical data tracking with date selection
- Responsive design optimized for mobile devices
- Interactive charts for visualizing nutrition data

## Setup

1. Clone this repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create a `.env` file in the root directory and add your OpenAI API key:
   ```
   OPENAI_API_KEY=your_api_key_here
   SECRET_KEY=your_flask_secret_key_here
   ```
5. Run the application:
   ```bash
   python app.py
   ```
6. Open your browser and navigate to `http://localhost:5000`

## Usage

1. Click "Start Camera" to activate your device's camera
2. Take a photo of your meal
3. Enter the weight of the meal in grams
4. Click "Analyze Meal" to get AI-powered nutritional analysis
5. Review the analysis and make any necessary adjustments
6. Confirm to save the meal to your daily log
7. View your daily totals in the table and chart below
8. Use the date selector to view historical data

## Technical Details

- Built with Flask and SQLite
- Uses OpenAI's GPT-4 Vision API for image analysis
- Mobile-first responsive design with Bootstrap 5
- Interactive charts using Chart.js
- Camera access using WebRTC APIs

## Security Notes

- Never commit your `.env` file or expose your API keys
- The application uses secure HTTPS for API communication
- Image data is processed locally before being sent to OpenAI
- Database is secured using SQLite's built-in security features

## Contributing

Feel free to submit issues and enhancement requests! 