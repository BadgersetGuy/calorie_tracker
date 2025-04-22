import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import openai
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import base64
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///meals.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'  # Use /tmp for cloud deployment
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Database Models
class Meal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    weight = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=True)
    calories = db.Column(db.Float, nullable=False)
    protein = db.Column(db.Float, nullable=False)
    carbs = db.Column(db.Float, nullable=False)
    fat = db.Column(db.Float, nullable=False)
    image_data = db.Column(db.Text, nullable=True)  # Store image as base64

# Create database tables
with app.app_context():
    db.create_all()

def analyze_image_with_openai(image_data, weight):
    try:
        if not os.getenv('OPENAI_API_KEY'):
            logger.error("OpenAI API key is not set")
            raise ValueError("OpenAI API key is not configured")
        
        # Set API key directly
        openai.api_key = os.getenv('OPENAI_API_KEY')
            
        logger.debug(f"Sending image to OpenAI (length: {len(image_data)})")
        response = openai.ChatCompletion.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Analyze this meal that weighs {weight}g. Identify the ingredients and estimate its nutritional content."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}"
                            }
                        }
                    ]
                }
            ],
            functions=[
                {
                    "name": "analyze_meal",
                    "description": "Analyze a meal's ingredients and nutritional content",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "Detailed description of the identified ingredients and meal composition"
                            },
                            "calories": {
                                "type": "number",
                                "description": "Total calories in the meal"
                            },
                            "protein": {
                                "type": "number",
                                "description": "Protein content in grams"
                            },
                            "carbs": {
                                "type": "number",
                                "description": "Carbohydrate content in grams"
                            },
                            "fat": {
                                "type": "number",
                                "description": "Fat content in grams"
                            }
                        },
                        "required": ["description", "calories", "protein", "carbs", "fat"]
                    }
                }
            ],
            function_call={"name": "analyze_meal"},
            max_tokens=5000
        )
        logger.debug("Successfully received response from OpenAI")
        
        # Extract the function call arguments which will be our structured output
        function_args = response.choices[0].message['function_call']['arguments']
        logger.debug(f"Function arguments: {function_args}")
        return function_args
        
    except Exception as e:
        logger.error(f"Error in analyze_image_with_openai: {str(e)}")
        raise

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_meal():
    try:
        logger.debug("Starting upload_meal endpoint")
        if 'meal_photo' not in request.files:
            logger.warning("No meal_photo in request.files")
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['meal_photo']
        weight = float(request.form.get('weight', 0))
        
        if file.filename == '':
            logger.warning("Empty filename")
            return jsonify({'error': 'No file selected'}), 400
        
        if file:
            try:
                # Read and encode the image
                file_data = file.read()
                logger.debug(f"Read file data (size: {len(file_data)} bytes)")
                image_data = base64.b64encode(file_data).decode('utf-8')
                logger.debug(f"Encoded image to base64 (length: {len(image_data)})")
                
                # Analyze image with OpenAI
                analysis_result = analyze_image_with_openai(image_data, weight)
                logger.debug("Successfully analyzed image")
                
                return jsonify({
                    'analysis': analysis_result,
                    'image_data': image_data
                })
            except Exception as e:
                logger.error(f"Error processing file: {str(e)}")
                return jsonify({'error': f'Error processing image: {str(e)}'}), 500
        
        return jsonify({'error': 'Invalid file'}), 400
    except Exception as e:
        logger.error(f"Unexpected error in upload_meal: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/save_meal', methods=['POST'])
def save_meal():
    data = request.json
    
    new_meal = Meal(
        weight=data['weight'],
        description=data['description'],
        calories=data['calories'],
        protein=data['protein'],
        carbs=data['carbs'],
        fat=data['fat'],
        image_data=data.get('image_data')
    )
    
    db.session.add(new_meal)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/meals')
def get_meals():
    date = request.args.get('date', datetime.today().strftime('%Y-%m-%d'))
    meals = Meal.query.filter(
        db.func.date(Meal.date) == date
    ).all()
    
    return jsonify([{
        'id': meal.id,
        'date': meal.date.isoformat(),
        'weight': meal.weight,
        'description': meal.description,
        'calories': meal.calories,
        'protein': meal.protein,
        'carbs': meal.carbs,
        'fat': meal.fat,
        'image_data': meal.image_data
    } for meal in meals])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000))) 