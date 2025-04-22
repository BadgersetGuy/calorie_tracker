import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import openai
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import base64

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
    client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    try:
        response = client.chat.completions.create(
            model="gpt-4-vision-preview",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"This is a meal weighing {weight}g. Please identify the ingredients and estimate the macronutrients (protein, carbs, fat) and total calories. Return the response in JSON format with keys: description, calories, protein, carbs, fat"
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
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        return str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_meal():
    if 'meal_photo' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['meal_photo']
    weight = float(request.form.get('weight', 0))
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file:
        # Read and encode the image
        image_data = base64.b64encode(file.read()).decode('utf-8')
        
        # Analyze image with OpenAI
        analysis_result = analyze_image_with_openai(image_data, weight)
        
        return jsonify({
            'analysis': analysis_result,
            'image_data': image_data
        })

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