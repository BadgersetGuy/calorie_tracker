import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
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
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    meals = db.relationship('Meal', backref='user', lazy=True)

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
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# Create database tables
with app.app_context():
    db.create_all()

def analyze_image_with_openai(image_data, weight, meal_details=None):
    try:
        if not os.getenv('OPENAI_API_KEY'):
            logger.error("OpenAI API key is not set")
            raise ValueError("OpenAI API key is not configured")
        
        # Set API key directly
        openai.api_key = os.getenv('OPENAI_API_KEY')
        
        # Prepare the prompt based on whether meal details are provided
        prompt_text = f"This is a meal weighing {weight}g (not including the plate)."
        if meal_details:
            prompt_text += f" Additional details provided: {meal_details}."
        prompt_text += " Please identify the ingredients and estimate its nutritional content."
            
        logger.debug(f"Sending image to OpenAI (length: {len(image_data)})")
        response = openai.ChatCompletion.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt_text
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
                                "description": "Concise description of the identified ingredients and meal composition. Also a breakdown of each ingredients calories and estimated weight from total weight of the meal."
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
            max_tokens=15000
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
        meal_details = request.form.get('meal_details', '').strip()
        
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
                analysis_result = analyze_image_with_openai(
                    image_data, 
                    weight,
                    meal_details if meal_details else None
                )
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
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'User ID is required'}), 400
    
    new_meal = Meal(
        user_id=user_id,
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
    user_id = request.args.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'User ID is required'}), 400
    
    meals = Meal.query.filter(
        db.func.date(Meal.date) == date,
        Meal.user_id == user_id
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

@app.route('/meal_history')
def get_meal_history():
    try:
        # Get date range and user_id from query parameters
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        user_id = request.args.get('user_id')
        
        if not all([start_date, end_date, user_id]):
            raise ValueError("Start date, end date, and user ID are required")
            
        # Convert string dates to datetime objects
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
        end_date = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)  # Include the end date
        
        # Query meals within the date range for specific user
        meals = Meal.query.filter(
            Meal.date >= start_date,
            Meal.date < end_date,
            Meal.user_id == user_id
        ).order_by(Meal.date).all()
        
        # Group meals by date
        meals_by_date = {}
        
        # Initialize all dates in the range
        current_date = start_date
        while current_date < end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            meals_by_date[date_str] = {
                'calories': 0,
                'protein': 0,
                'carbs': 0,
                'fat': 0
            }
            current_date += timedelta(days=1)
        
        # Sum up the meals for each date
        for meal in meals:
            date_str = meal.date.strftime('%Y-%m-%d')
            meals_by_date[date_str]['calories'] += meal.calories
            meals_by_date[date_str]['protein'] += meal.protein
            meals_by_date[date_str]['carbs'] += meal.carbs
            meals_by_date[date_str]['fat'] += meal.fat

        # Sort dates and prepare data for charts
        dates = sorted(meals_by_date.keys())
        
        return jsonify({
            'dates': dates,  # These are now in YYYY-MM-DD format
            'calories': [meals_by_date[date]['calories'] for date in dates],
            'protein': [meals_by_date[date]['protein'] for date in dates],
            'carbs': [meals_by_date[date]['carbs'] for date in dates],
            'fat': [meals_by_date[date]['fat'] for date in dates]
        })
        
    except ValueError as e:
        logger.error(f"Invalid date parameters: {str(e)}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error getting meal history: {str(e)}")
        return jsonify({'error': str(e)}), 500

# User management endpoints
@app.route('/users', methods=['GET'])
def get_users():
    users = User.query.order_by(User.username).all()
    return jsonify([{
        'id': user.id,
        'username': user.username,
        'created_at': user.created_at.isoformat()
    } for user in users])

@app.route('/users', methods=['POST'])
def create_user():
    data = request.json
    username = data.get('username')
    
    if not username:
        return jsonify({'error': 'Username is required'}), 400
        
    # Check if username already exists
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 400
    
    new_user = User(username=username)
    db.session.add(new_user)
    db.session.commit()
    
    return jsonify({
        'id': new_user.id,
        'username': new_user.username,
        'created_at': new_user.created_at.isoformat()
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000))) 