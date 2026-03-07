from flask import Flask, request, jsonify, send_file, redirect
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import os
import random
import json
from functools import wraps
import pdfplumber
import re
from dotenv import load_dotenv
from openai import OpenAI
from pdf_pipeline import extract_syllabus_structure

# Load environment variables
load_dotenv()

# Initialize OpenAI Client
openai_client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'mysql+mysqlconnector://root:root123@localhost/studymap')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = 'jwt-secret-key-change-in-production'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize extensions
# Configure CORS to allow requests from frontend on any port (development)
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:3000", "http://localhost:8000", "http://localhost:5000", "*"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True
    }
})
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

@jwt.invalid_token_loader
def invalid_token_callback(error):
    print(f"Invalid token: {error}")
    return jsonify({
        'error': 'Invalid token',
        'msg': error
    }), 422

@jwt.unauthorized_loader
def missing_token_callback(error):
    print(f"Missing token: {error}")
    return jsonify({
        'error': 'Authorization required',
        'msg': error
    }), 401

@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    print("Token has expired")
    return jsonify({
        'error': 'Token expired',
        'msg': 'The token has expired'
    }), 401

# ================================
# DATABASE MODELS
# ================================

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column('user_id', db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='student')  # 'student' or 'admin'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    syllabi = db.relationship('Syllabus', backref='user', lazy=True, cascade='all, delete-orphan')
    test_attempts = db.relationship('TestAttempt', backref='user', lazy=True, cascade='all, delete-orphan')
    streak = db.relationship('Streak', backref='user', uselist=False, cascade='all, delete-orphan')
    final_exam = db.relationship('FinalExam', backref='user', uselist=False, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'role': self.role,
            'joined': self.created_at.strftime('%Y-%m-%d')
        }


class Syllabus(db.Model):
    __tablename__ = 'syllabi'
    id = db.Column('syllabus_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255))
    filepath = db.Column(db.String(500))
    extracted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_accessed = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    subjects = db.relationship('Subject', backref='syllabus', lazy=True, cascade='all, delete-orphan')
    final_exam = db.relationship('FinalExam', backref='syllabus', uselist=False, cascade='all, delete-orphan')

    def to_dict(self, include_subjects=True):
        result = {
            'id': self.id,
            'name': self.name,
            'filename': self.filename,
            'extracted': self.extracted,
            'created_at': self.created_at.isoformat()
        }
        if include_subjects:
            result['subjects'] = [subject.to_dict() for subject in self.subjects]
        return result


class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column('subject_id', db.Integer, primary_key=True)
    syllabus_id = db.Column(db.Integer, db.ForeignKey('syllabi.syllabus_id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    order_index = db.Column(db.Integer, default=0)
    
    # Relationships
    topics = db.relationship('Topic', backref='subject', lazy=True, cascade='all, delete-orphan')

    def to_dict(self, include_topics=True):
        result = {
            'id': f's{self.id}',
            'name': self.name
        }
        if include_topics:
            result['topics'] = [topic.to_dict() for topic in sorted(self.topics, key=lambda t: t.order_index)]
        return result


class Topic(db.Model):
    __tablename__ = 'topics'
    id = db.Column('topic_id', db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.subject_id'), nullable=False)
    # parent_topic_id links a subtopic row back to its parent topic header.
    # NULL  → this row IS a topic heading (or a flat topic from PDF extraction).
    # non-NULL → this row IS a subtopic that can be tested.
    parent_topic_id = db.Column(db.Integer, db.ForeignKey('topics.topic_id'), nullable=True)
    name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default='pending')  # 'pending' or 'verified'
    score = db.Column(db.Integer)
    order_index = db.Column(db.Integer, default=0)

    # Relationships
    questions = db.relationship('Question', backref='topic', lazy=True, cascade='all, delete-orphan')
    test_attempts = db.relationship('TestAttempt', backref='topic', lazy=True, cascade='all, delete-orphan')
    # A topic heading may have child subtopics
    subtopics = db.relationship(
        'Topic',
        backref=db.backref('parent_topic', remote_side='Topic.id'),
        foreign_keys='Topic.parent_topic_id',
        lazy=True,
        cascade='all, delete-orphan'
    )

    def to_dict(self):
        result = {
            'id': f't{self.id}',
            'name': self.name,
            'status': self.status,
            'subject_id': f's{self.subject_id}',
            'parent_topic_id': f't{self.parent_topic_id}' if self.parent_topic_id else None
        }
        if self.score is not None:
            result['score'] = self.score
        return result


class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column('question_id', db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topics.topic_id'), nullable=False)
    question = db.Column(db.Text, nullable=False)
    options = db.Column(db.Text, nullable=False)  # JSON string
    correct_answer = db.Column(db.Integer, nullable=False)  # Index of correct option

    def to_dict(self, include_answer=False):
        result = {
            'id': self.id,
            'question': self.question,
            'options': json.loads(self.options)
        }
        if include_answer:
            result['correct_answer'] = self.correct_answer
        return result


class TestAttempt(db.Model):
    __tablename__ = 'test_attempts'
    id = db.Column('test_attempt_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    topic_id = db.Column(db.Integer, db.ForeignKey('topics.topic_id'), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    passed = db.Column(db.Boolean, default=False)
    answers = db.Column(db.Text)  # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'topic_id': self.topic_id,
            'score': self.score,
            'passed': self.passed,
            'created_at': self.created_at.isoformat()
        }


class Streak(db.Model):
    __tablename__ = 'streaks'
    id = db.Column('streak_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    current_streak = db.Column(db.Integer, default=0)
    longest_streak = db.Column(db.Integer, default=0)
    last_activity_date = db.Column(db.Date)
    activity_dates = db.Column(db.Text)  # JSON string of dates

    def to_dict(self):
        activity_dates = json.loads(self.activity_dates) if self.activity_dates else []
        return {
            'currentStreak': self.current_streak,
            'longestStreak': self.longest_streak,
            'lastActivityDate': self.last_activity_date.isoformat() if self.last_activity_date else None,
            'activityDates': activity_dates
        }


class FinalExam(db.Model):
    __tablename__ = 'final_exams'
    id = db.Column('final_exam_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    syllabus_id = db.Column(db.Integer, db.ForeignKey('syllabi.syllabus_id'), nullable=False)
    score = db.Column(db.Integer)
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'syllabus_id': self.syllabus_id,
            'score': self.score,
            'completed': self.completed,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }


# ================================
# HELPER FUNCTIONS
# ================================

def extract_text_from_pdf(filepath):
    """Extract text from PDF file using pdfplumber"""
    try:
        text = ''
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + '\n'
        
        # If extraction failed or returned very little text, it might be an image-based PDF
        if len(text.strip()) < 10:
            print(f"Warning: Very little text extracted from {filepath}. The PDF might be image-based.")
            return "Note: This PDF appears to be image-based or contains no selectable text."
            
        return text
    except Exception as e:
        print(f"Error extracting PDF: {str(e)}")
        return f"Error extracting text: {str(e)}"


def parse_syllabus_with_ai(text):
    if not os.environ.get('OPENAI_API_KEY') or os.environ.get('OPENAI_API_KEY') == 'your-openai-api-key':
        print("Warning: OpenAI API Key not configured. Falling back to manual parsing.")
        return parse_syllabus_content(text)
        
    try:
        # Use gpt-4o for better accuracy and longer context
        prompt = f"""
        Analyze the full syllabus text and extract a deep, accurate academic hierarchy.
        
        STRICT RULES:
        1. Ignore noise: Exclude outcomes, objectives, assessments, references, schedules, weeks, page numbers, contact info, and generic headers.
        2. Capture hierarchy: Identify SUBJECTS/UNITS -> TOPICS -> SUBTOPICS.
        3. Be comprehensive: Don't miss valid teachable concepts.
        4. Normalize names: Clean up numbering (e.g., "1.1 Topic" -> "Topic").
        
        Output JSON ONLY:
        {{
          "subjects": [
            {{
              "name": "Subject Name",
              "topics": [
                {{
                  "name": "Main Topic",
                  "subtopics": [
                    {{"name": "Subtopic 1"}},
                    {{"name": "Subtopic 2"}}
                  ]
                }}
              ]
            }}
          ]
        }}

        Syllabus Content:
        {text[:15000]}
        """

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert academic curriculum parser. You extract precise, hierarchical syllabus structures."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            timeout=60.0
        )

        content_str = response.choices[0].message.content
        print(f"AI Response received: {content_str[:100]}...")
        result = json.loads(content_str)
        
        # Handle different potential JSON structures from AI
        if isinstance(result, dict):
            if "subjects" in result:
                subjects = result["subjects"]
                return clean_subjects(subjects)
            if "syllabus" in result:
                subjects = result["syllabus"]
                return clean_subjects(subjects)
            if "name" in result and "topics" in result:
                subjects = [result]
                return clean_subjects(subjects)
        elif isinstance(result, list):
            return clean_subjects(result)
            
        return parse_syllabus_content(text)

    except Exception as e:
        print(f"OpenAI parsing error: {str(e)}")
        # Fallback to manual parsing if AI fails
        return parse_syllabus_content(text)

def _is_valid_topic_name(name: str) -> bool:
    if not name:
        return False
    n = name.strip()
    if len(n) < 3 or len(n) > 120:
        return False
    lower = n.lower()
    bad_keywords = [
        'assessment', 'evaluation', 'credit', 'credits', 'reference', 'bibliography', 'textbook',
        'outcome', 'objectives', 'prerequisite', 'schedule', 'week', 'page', 'contact', 'email',
        'phone', 'office', 'exam', 'project submission', 'assignment', 'grading', 'marks',
        'syllabus', 'chapter', 'unit', 'section'
    ]
    if any(k in lower for k in bad_keywords):
        return False
    noisy_patterns = ['http://', 'https://']
    if any(p in lower for p in noisy_patterns):
        return False
    punct_ratio = sum(1 for c in n if c in ',;:()[]{}|\\/') / max(1, len(n))
    if punct_ratio > 0.25:
        return False
    return True

def clean_subjects(subjects):
    cleaned = []
    for s in subjects or []:
        name = (s.get('name') or '').strip()
        topics = s.get('topics') or []
        seen = set()
        filtered_topics = []
        for t in topics:
            tname = (t.get('name') or '').strip()
            if not _is_valid_topic_name(tname):
                continue
            key = tname.lower()
            if key in seen:
                continue
            seen.add(key)
            subtopics = []
            for st in (t.get('subtopics') or []):
                stname = (st.get('name') or '').strip()
                if not _is_valid_topic_name(stname):
                    continue
                skey = f"{key}:{stname.lower()}"
                if skey in seen:
                    continue
                seen.add(skey)
                subtopics.append({'name': stname})
            filtered_topics.append({'name': tname, 'subtopics': subtopics})
        cleaned.append({
            'name': name or 'Untitled',
            'topics': filtered_topics
        })
    return cleaned

def parse_syllabus_content(text):
    subjects = []
    lines = text.split('\n')
    current_subject = None
    current_topic = None
    
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        
        subject_match = re.match(r'^(?:Chapter\s+|UNIT\s+)?([IVXLCDM\d]+)[\.\:\)]?\s*(.+)$', line, re.IGNORECASE)
        if subject_match and len(line) < 120:
            if current_subject:
                subjects.append(current_subject)
            current_subject = {'name': subject_match.group(2).strip() or f"Section {subject_match.group(1)}", 'topics': []}
            current_topic = None
            continue
        
        if current_subject:
            subtopic_numbered = re.match(r'^\d+\.\d+\s+(.+)$', line)  # e.g., 1.2 Subtopic
            topic_numbered = re.match(r'^\d+\.\s+(.+)$', line)       # e.g., 1. Topic
            bullet = re.match(r'^(?:[\-\•\*\u2022]|–|—)\s*(.+)$', line)
            
            if topic_numbered and len(line) < 200:
                name = topic_numbered.group(1).strip()
                if _is_valid_topic_name(name):
                    current_topic = {'name': name, 'subtopics': []}
                    current_subject['topics'].append(current_topic)
                continue
            
            if subtopic_numbered and len(line) < 200 and current_topic:
                st = subtopic_numbered.group(1).strip()
                if _is_valid_topic_name(st):
                    current_topic.setdefault('subtopics', []).append({'name': st})
                continue
            
            if bullet and len(line) < 200:
                name = bullet.group(1).strip()
                if current_topic and _is_valid_topic_name(name):
                    current_topic.setdefault('subtopics', []).append({'name': name})
                elif _is_valid_topic_name(name):
                    current_topic = {'name': name, 'subtopics': []}
                    current_subject['topics'].append(current_topic)
                continue
            
            if len(line) < 120 and _is_valid_topic_name(line):
                if current_topic is None:
                    current_topic = {'name': line, 'subtopics': []}
                    current_subject['topics'].append(current_topic)
                else:
                    current_topic.setdefault('subtopics', []).append({'name': line})
    
    if current_subject:
        subjects.append(current_subject)
    
    if not subjects:
        subjects = [{'name': 'General Topics', 'topics': []}]
    
    return clean_subjects(subjects)

@app.route('/api/syllabus/structure', methods=['GET'])
@jwt_required()
def get_active_syllabus_structure():
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        syllabus = Syllabus.query.filter_by(user_id=user_id).order_by(Syllabus.last_accessed.desc()).first()
        if not syllabus:
            return jsonify({'structure': None}), 200
        subjects = extract_syllabus_structure(
            syllabus.filepath,
            syllabus_id=syllabus.id,
            openai_client=openai_client
        ) if syllabus.filepath else []
        return jsonify({'structure': {'id': syllabus.id, 'name': syllabus.name, 'subjects': subjects}}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/syllabus/structure/<int:syllabus_id>', methods=['GET'])
@jwt_required()
def get_syllabus_structure_by_id(syllabus_id):
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        syllabus = Syllabus.query.filter_by(id=syllabus_id, user_id=user_id).first()
        if not syllabus:
            return jsonify({'error': 'Syllabus not found'}), 404
        subjects = extract_syllabus_structure(
            syllabus.filepath,
            syllabus_id=syllabus.id,
            openai_client=openai_client
        ) if syllabus.filepath else []
        return jsonify({'structure': {'id': syllabus.id, 'name': syllabus.name, 'subjects': subjects}}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def generate_questions(topic_name, count=5):
    """Generate sample questions for a topic"""
    # Sample question templates
    templates = [
        {
            'question': f'What is the primary concept of {topic_name}?',
            'options': [
                f'Basic principle of {topic_name}',
                f'Advanced application of {topic_name}',
                f'Historical context of {topic_name}',
                f'Future implications of {topic_name}'
            ]
        },
        {
            'question': f'Which statement best describes {topic_name}?',
            'options': [
                'First definition option',
                'Second definition option',
                'Third definition option',
                'Fourth definition option'
            ]
        },
        {
            'question': f'What are the key components of {topic_name}?',
            'options': [
                'Component A and B',
                'Component C and D',
                'Component E and F',
                'All of the above'
            ]
        },
        {
            'question': f'How does {topic_name} relate to practical applications?',
            'options': [
                'Through direct implementation',
                'Through theoretical framework',
                'Through empirical evidence',
                'Through case studies'
            ]
        },
        {
            'question': f'What is the significance of {topic_name}?',
            'options': [
                'It forms the foundation',
                'It provides practical tools',
                'It offers theoretical insights',
                'All of the above'
            ]
        }
    ]
    
    questions = []
    for i in range(count):
        template = templates[i % len(templates)]
        questions.append({
            'question': template['question'],
            'options': template['options'],
            'correct_answer': random.randint(0, 3)
        })
    
    return questions


# ================================
# AUTHENTICATION ROUTES
# ================================

@app.route('/api/auth/register', methods=['POST'])
def register():
    """Register a new user"""
    try:
        data = request.get_json()
        print(f"Registration attempt for: {data.get('email')}")
        
        if not data or not data.get('email') or not data.get('password') or not data.get('name'):
            return jsonify({'error': 'All fields are required'}), 400
            
        if User.query.filter_by(email=data['email']).first():
            return jsonify({'error': 'Email already exists'}), 400
            
        hashed_password = bcrypt.generate_password_hash(data['password']).decode('utf-8')
        user = User(
            name=data['name'],
            email=data['email'],
            password=hashed_password
        )
        
        db.session.add(user)
        db.session.flush() # Flush to get the ID
        print(f"User created with ID: {user.id}")
        
        # Initialize streak
        streak = Streak(user_id=user.id)
        db.session.add(streak)
        
        db.session.commit()
        
        # Create access token
        access_token = create_access_token(identity=str(user.id))
        print(f"Registration successful, token created for user {user.id}")
        
        return jsonify({
            'token': access_token,
            'user': user.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/auth/login', methods=['POST'])
def login():
    """Authenticate user and return token"""
    try:
        data = request.get_json()
        print(f"Login attempt for: {data.get('email')}")
        
        if not data or not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Email and password required'}), 400
        
        user = User.query.filter_by(email=data['email']).first()
        
        if not user or not bcrypt.check_password_hash(user.password, data['password']):
            print("Invalid credentials")
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Create access token
        access_token = create_access_token(identity=str(user.id))
        print(f"Login successful, token created for user {user.id}")
        
        return jsonify({
            'token': access_token,
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current logged-in user"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({'user': user.to_dict()}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500




# ================================
# SYLLABUS ROUTES
# ================================

@app.route('/api/syllabus', methods=['GET'])
@jwt_required()
def get_syllabi():
    """Get all user's syllabi"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        syllabi = Syllabus.query.filter_by(user_id=user_id).order_by(Syllabus.last_accessed.desc()).all()
        return jsonify({'syllabi': [s.to_dict(include_subjects=False) for s in syllabi]}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/syllabus/active', methods=['GET'])
@jwt_required()
def get_active_syllabus():
    """Get user's most recent/active syllabus"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        syllabus = Syllabus.query.filter_by(user_id=user_id).order_by(Syllabus.last_accessed.desc()).first()
        if not syllabus:
            return jsonify({'syllabus': None}), 200
        return jsonify({'syllabus': syllabus.to_dict()}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/syllabus/<int:syllabus_id>', methods=['DELETE'])
@jwt_required()
def delete_syllabus(syllabus_id):
    """Delete a specific syllabus"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        syllabus = Syllabus.query.filter_by(id=syllabus_id, user_id=user_id).first()
        
        if not syllabus:
            return jsonify({'error': 'Syllabus not found'}), 404
            
        # Delete physical file if exists
        if syllabus.filepath and os.path.exists(syllabus.filepath):
            try:
                os.remove(syllabus.filepath)
            except Exception as e:
                print(f"Error deleting file: {e}")
        
        db.session.delete(syllabus)
        db.session.commit()
        
        return jsonify({'message': 'Syllabus deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/syllabus/<int:syllabus_id>', methods=['GET'])
@jwt_required()
def get_syllabus_by_id(syllabus_id):
    """Get specific syllabus by ID"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        syllabus = Syllabus.query.filter_by(id=syllabus_id, user_id=user_id).first()
        
        if not syllabus:
            return jsonify({'error': 'Syllabus not found'}), 404
            
        # Update last accessed
        syllabus.last_accessed = datetime.utcnow()
        db.session.commit()
            
        return jsonify({'syllabus': syllabus.to_dict()}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/syllabus/upload', methods=['POST'])
@jwt_required()
def upload_syllabus():
    """Upload a new syllabus and extract subjects/topics"""
    print("Upload request received!")
    print(f"Headers: {request.headers.get('Authorization')}")
    try:
        user_id = int(get_jwt_identity())
        print(f"User ID from JWT: {user_id}")
        
        user = User.query.get(user_id)
        if not user:
            print(f"User ID {user_id} not found in DB")
            return jsonify({'error': 'User session invalid. Please log out and log in again.'}), 401
            
        if 'file' not in request.files:
            print("No file in request")
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.endswith('.pdf'):
            return jsonify({'error': 'Only PDF files are allowed'}), 400
        
        # Save file
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{user_id}_{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Extract and parse syllabus using the robust pipeline
        print(f"Running PDF pipeline on: {filepath}")
        parsed_subjects = extract_syllabus_structure(
            filepath,
            syllabus_id=None,          # real ID assigned after flush below
            openai_client=openai_client
        )
        print(f"Pipeline returned {len(parsed_subjects) if parsed_subjects else 0} units")
        
        # Create syllabus record
        syllabus_name = request.form.get('name', file.filename.replace('.pdf', ''))
        syllabus = Syllabus(
            user_id=user_id,
            name=syllabus_name,
            filename=filename,
            filepath=filepath,
            extracted=False
        )
        db.session.add(syllabus)
        db.session.flush()
        
        # Save extracted subjects and topics temporarily
        if parsed_subjects:
            for idx, subject_data in enumerate(parsed_subjects):
                subject = Subject(
                    syllabus_id=syllabus.id,
                    name=subject_data.get('name', f'Subject {idx+1}'),
                    order_index=idx
                )
                db.session.add(subject)
                db.session.flush()
                
                topics = subject_data.get('topics', [])
                for topic_idx, topic_data in enumerate(topics):
                    topic = Topic(
                        subject_id=subject.id,
                        name=topic_data.get('name', f'Topic {topic_idx+1}'),
                        status='pending',
                        order_index=topic_idx
                    )
                    db.session.add(topic)
                    db.session.flush()
                    
                    # Generate questions for this topic
                    questions = generate_questions(topic.name, 5)
                    for question_data in questions:
                        question = Question(
                            topic_id=topic.id,
                            question=question_data['question'],
                            options=json.dumps(question_data['options']),
                            correct_answer=question_data['correct_answer']
                        )
                        db.session.add(question)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Syllabus uploaded successfully',
            'syllabus': syllabus.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/syllabus/extract', methods=['POST'])
@jwt_required()
def extract_syllabus():
    """Finalize syllabus extraction with user modifications"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        data = request.get_json()
        
        syllabus_id = data.get('syllabusId')
        subjects_data = data.get('subjects', [])
        
        if not syllabus_id:
            return jsonify({'error': 'Syllabus ID required'}), 400
        
        syllabus = Syllabus.query.filter_by(id=syllabus_id, user_id=user_id).first()
        
        if not syllabus:
            return jsonify({'error': 'Syllabus not found'}), 404
        
        # Delete existing subjects/topics
        Subject.query.filter_by(syllabus_id=syllabus.id).delete()
        
        # Create new subjects and topics
        def save_topic_and_questions(name, subject_id, order_index):
            topic = Topic(
                subject_id=subject_id,
                name=name,
                status='pending',
                order_index=order_index
            )
            db.session.add(topic)
            db.session.flush()
            
            # Generate questions for this topic
            questions = generate_questions(topic.name, 5)
            for question_data in questions:
                question = Question(
                    topic_id=topic.id,
                    question=question_data['question'],
                    options=json.dumps(question_data['options']),
                    correct_answer=question_data['correct_answer']
                )
                db.session.add(question)
            return topic

        for idx, subject_data in enumerate(subjects_data):
            subject = Subject(
                syllabus_id=syllabus.id,
                name=subject_data['name'],
                order_index=idx
            )
            db.session.add(subject)
            db.session.flush()
            
            current_order = 0
            for topic_data in subject_data.get('topics', []):
                # Save main topic
                save_topic_and_questions(topic_data['name'], subject.id, current_order)
                current_order += 1
                
                # Save subtopics as separate topics (flat in DB, but allows testing)
                for sub_data in topic_data.get('subtopics', []):
                    save_topic_and_questions(sub_data['name'], subject.id, current_order)
                    current_order += 1
        
        syllabus.extracted = True
        db.session.commit()
        
        return jsonify({
            'message': 'Syllabus extracted successfully',
            'syllabus': syllabus.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ================================
# MANUAL SYLLABUS ROUTES
# ================================

@app.route('/api/syllabus/manual', methods=['POST'])
@jwt_required()
def save_manual_syllabus():
    """
    Save a manually entered syllabus following the hierarchy:
      Unit (Subject) -> Topic -> Subtopic

    Expected JSON body:
    {
      "syllabusName": "My Course",
      "units": [
        {
          "name": "Unit 1",
          "topics": [
            {
              "name": "Introduction",
              "subtopics": [
                "Introduction to Python",
                "Data Types in Python",
                "Operators in Python"
              ]
            }
          ]
        }
      ]
    }
    """
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User session invalid. Please log out and log in again.'}), 401

        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # ── Validate syllabus name ──────────────────────────────────────────
        syllabus_name = (data.get('syllabusName') or '').strip()
        if not syllabus_name:
            return jsonify({'error': 'Syllabus name is required'}), 400

        units_data = data.get('units', [])
        if not units_data:
            return jsonify({'error': 'At least one unit with a topic is required'}), 400

        # ── Create the Syllabus record (no PDF path for manual entry) ───────
        syllabus = Syllabus(
            user_id=user_id,
            name=syllabus_name,
            filename=None,
            filepath=None,
            extracted=True      # Mark as already processed
        )
        db.session.add(syllabus)
        db.session.flush()      # Assign syllabus.id

        # ── Helper: create a testable subtopic row ──────────────────────────
        def create_subtopic_row(subtopic_name, subject_id, parent_topic_id, order_index):
            """Creates a Topic row with parent_topic_id set (= a proper subtopic)."""
            subtopic = Topic(
                subject_id=subject_id,
                parent_topic_id=parent_topic_id,
                name=subtopic_name,
                status='pending',
                order_index=order_index
            )
            db.session.add(subtopic)
            db.session.flush()  # Assign subtopic.id

            # Auto-generate 5 MCQ questions for this subtopic
            questions = generate_questions(subtopic_name, 5)
            for q_data in questions:
                db.session.add(Question(
                    topic_id=subtopic.id,
                    question=q_data['question'],
                    options=json.dumps(q_data['options']),
                    correct_answer=q_data['correct_answer']
                ))
            return subtopic

        # ── Persist units → topics → subtopics ─────────────────────────────
        for u_idx, unit_data in enumerate(units_data):
            unit_name = (unit_data.get('name') or '').strip()
            if not unit_name:
                return jsonify({'error': f'Unit name cannot be empty (index {u_idx})'}), 400

            # Each Unit maps to a Subject row
            subject = Subject(
                syllabus_id=syllabus.id,
                name=unit_name,
                order_index=u_idx
            )
            db.session.add(subject)
            db.session.flush()  # Assign subject.id

            topics_data = unit_data.get('topics', [])
            for t_idx, topic_data in enumerate(topics_data):
                topic_name = (topic_data.get('name') or '').strip()
                if not topic_name:
                    return jsonify({'error': f'Topic name cannot be empty (unit: {unit_name})'}), 400

                subtopics = topic_data.get('subtopics', [])
                if not subtopics:
                    return jsonify({'error': f'Topic "{topic_name}" must have at least one subtopic'}), 400

                # Create the Topic heading row (parent_topic_id = NULL, not testable)
                topic_row = Topic(
                    subject_id=subject.id,
                    parent_topic_id=None,
                    name=topic_name,
                    status='pending',
                    order_index=t_idx
                )
                db.session.add(topic_row)
                db.session.flush()  # Assign topic_row.id

                # Create each subtopic as a child Topic row
                for st_idx, st_name in enumerate(subtopics):
                    st_name = st_name.strip()
                    if not st_name:
                        continue  # skip blank
                    create_subtopic_row(
                        subtopic_name=st_name,
                        subject_id=subject.id,
                        parent_topic_id=topic_row.id,
                        order_index=st_idx
                    )

        db.session.commit()

        return jsonify({
            'message': 'Manual syllabus saved successfully',
            'syllabus': syllabus.to_dict(include_subjects=False)
        }), 201

    except Exception as e:
        db.session.rollback()
        print(f'Manual syllabus save error: {str(e)}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/syllabus/manual/structure/<int:syllabus_id>', methods=['GET'])
@jwt_required()
def get_manual_syllabus_structure(syllabus_id):
    """
    Return the full Unit → Topic → Subtopic hierarchy for a manually-entered
    syllabus in a format the front-end can render with "Start Test" buttons.
    """
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User session invalid.'}), 401

        syllabus = Syllabus.query.filter_by(id=syllabus_id, user_id=user_id).first()
        if not syllabus:
            return jsonify({'error': 'Syllabus not found'}), 404

        # Update last_accessed
        syllabus.last_accessed = datetime.utcnow()
        db.session.commit()

        units = []
        for subject in sorted(syllabus.subjects, key=lambda s: s.order_index):
            # Topic headings: parent_topic_id is NULL
            topic_headings = Topic.query.filter_by(
                subject_id=subject.id,
                parent_topic_id=None
            ).order_by(Topic.order_index).all()

            topics_out = []
            for th in topic_headings:
                # Children: subtopics whose parent_topic_id == th.id
                subs = Topic.query.filter_by(
                    parent_topic_id=th.id
                ).order_by(Topic.order_index).all()

                subtopics_out = []
                for st in subs:
                    subtopics_out.append({
                        'id': f't{st.id}',
                        'name': st.name,
                        'status': st.status,
                        'score': st.score
                    })

                topics_out.append({
                    'id': f't{th.id}',
                    'name': th.name,
                    'subtopics': subtopics_out
                })

            units.append({
                'id': f's{subject.id}',
                'name': subject.name,
                'topics': topics_out
            })

        return jsonify({
            'syllabus': {
                'id': syllabus.id,
                'name': syllabus.name
            },
            'units': units
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ================================
# TEST ROUTES
# ================================

@app.route('/api/tests/questions/<topic_id>', methods=['GET'])
@jwt_required()
def get_questions(topic_id):
    """Get questions for a topic"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        
        # Extract numeric ID from 't123' format
        numeric_id = int(topic_id.replace('t', ''))
        
        topic = Topic.query.get(numeric_id)
        
        if not topic:
            return jsonify({'error': 'Topic not found'}), 404
        
        # Verify user owns this topic's syllabus
        syllabus = Syllabus.query.join(Subject).filter(
            Subject.id == topic.subject_id,
            Syllabus.user_id == user_id
        ).first()
        
        if not syllabus:
            return jsonify({'error': 'Unauthorized'}), 403
        
        questions = Question.query.filter_by(topic_id=topic.id).all()
        
        if not questions:
            # Generate questions on the fly if missing
            questions_data = generate_questions(topic.name, 5)
            for q_data in questions_data:
                question = Question(
                    topic_id=topic.id,
                    question=q_data['question'],
                    options=json.dumps(q_data['options']),
                    correct_answer=q_data['correct_answer']
                )
                db.session.add(question)
                questions.append(question)
            db.session.commit()
        
        return jsonify({
            'questions': [q.to_dict(include_answer=False) for q in questions]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tests/submit', methods=['POST'])
@jwt_required()
def submit_test():
    """Submit test answers"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        data = request.get_json()
        
        topic_id = data.get('topicId')
        answers = data.get('answers', [])
        
        # Extract numeric ID
        numeric_id = int(topic_id.replace('t', ''))
        
        topic = Topic.query.get(numeric_id)
        
        if not topic:
            return jsonify({'error': 'Topic not found'}), 404
            
        # Verify user owns this topic's syllabus
        syllabus = Syllabus.query.join(Subject).filter(
            Subject.id == topic.subject_id,
            Syllabus.user_id == user_id
        ).first()
        
        if not syllabus:
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Get questions and calculate score
        questions = Question.query.filter_by(topic_id=topic.id).all()
        correct_count = 0
        results = []

        for idx, question in enumerate(questions):
            user_answer = answers[idx] if idx < len(answers) else None
            is_correct = (user_answer is not None) and (question.correct_answer == user_answer)
            if is_correct:
                correct_count += 1
            results.append({
                'question': question.question,
                'options': json.loads(question.options),
                'correctAnswer': question.correct_answer,
                'userAnswer': user_answer,
                'isCorrect': is_correct
            })

        score = int((correct_count / len(questions)) * 100) if questions else 0
        passed = score >= 70
        
        # Save test attempt
        attempt = TestAttempt(
            user_id=user_id,
            topic_id=topic.id,
            score=score,
            passed=passed,
            answers=json.dumps(answers)
        )
        db.session.add(attempt)
        
        # Update topic status if passed
        if passed:
            topic.status = 'verified'
            if topic.score is None or score > topic.score:
                topic.score = score
        
        db.session.commit()
        
        return jsonify({
            'score': score,
            'passed': passed,
            'correct': correct_count,
            'total': len(questions),
            'results': results
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ================================
# ANALYTICS ROUTES
# ================================

@app.route('/api/analytics/stats', methods=['GET'])
@jwt_required()
def get_stats():
    """Get user analytics stats"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        
        # Get syllabus
        syllabus = Syllabus.query.filter_by(user_id=user_id).order_by(Syllabus.last_accessed.desc()).first()
        
        if not syllabus:
            return jsonify({
                'totalTopics': 0,
                'verifiedTopics': 0,
                'averageScore': 0,
                'testsCompleted': 0,
                'subjectProgress': []
            }), 200
        
        # Count topics
        total_topics = Topic.query.join(Subject).filter(Subject.syllabus_id == syllabus.id).count()
        verified_topics = Topic.query.join(Subject).filter(
            Subject.syllabus_id == syllabus.id,
            Topic.status == 'verified'
        ).count()
        
        # Get test attempts for THIS syllabus
        attempts = TestAttempt.query.join(Topic).join(Subject).filter(
            TestAttempt.user_id == user_id,
            Subject.syllabus_id == syllabus.id
        ).all()
        
        tests_completed = len(attempts)
        average_score = int(sum(a.score for a in attempts) / len(attempts)) if attempts else 0
        
        # Subject progress
        subjects = Subject.query.filter_by(syllabus_id=syllabus.id).all()
        subject_progress = []
        
        for subject in subjects:
            total = len(subject.topics)
            verified = sum(1 for t in subject.topics if t.status == 'verified')
            percentage = int((verified / total) * 100) if total > 0 else 0
            
            subject_progress.append({
                'name': subject.name,
                'total': total,
                'verified': verified,
                'percentage': percentage
            })
        
        return jsonify({
            'totalTopics': total_topics,
            'verifiedTopics': verified_topics,
            'averageScore': average_score,
            'testsCompleted': tests_completed,
            'subjectProgress': subject_progress
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ================================
# STREAK ROUTES
# ================================

@app.route('/api/streaks', methods=['GET'])
@jwt_required()
def get_streak():
    """Get user's streak data"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        
        streak = Streak.query.filter_by(user_id=user_id).first()
        
        if not streak:
            # Create initial streak
            streak = Streak(
                user_id=user_id,
                current_streak=0,
                longest_streak=0,
                activity_dates='[]'
            )
            db.session.add(streak)
            db.session.commit()
        
        return jsonify({'streak': streak.to_dict()}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/streaks/update', methods=['POST'])
@jwt_required()
def update_streak():
    """Update user's streak"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        today = datetime.utcnow().date()
        
        streak = Streak.query.filter_by(user_id=user_id).first()
        
        if not streak:
            streak = Streak(
                user_id=user_id,
                current_streak=1,
                longest_streak=1,
                last_activity_date=today,
                activity_dates=json.dumps([today.isoformat()])
            )
            db.session.add(streak)
        else:
            activity_dates = json.loads(streak.activity_dates) if streak.activity_dates else []
            today_str = today.isoformat()
            
            # Check if already updated today
            if today_str not in activity_dates:
                activity_dates.append(today_str)
                
                # Update streak logic
                if streak.last_activity_date:
                    days_diff = (today - streak.last_activity_date).days
                    
                    if days_diff == 1:
                        # Consecutive day
                        streak.current_streak += 1
                    elif days_diff > 1:
                        # Streak broken
                        streak.current_streak = 1
                    # Same day (days_diff == 0) - no change
                else:
                    streak.current_streak = 1
                
                # Update longest streak
                if streak.current_streak > streak.longest_streak:
                    streak.longest_streak = streak.current_streak
                
                streak.last_activity_date = today
                streak.activity_dates = json.dumps(activity_dates[-365:])  # Keep last year
        
        db.session.commit()
        
        return jsonify({'streak': streak.to_dict()}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ================================
# FINAL EXAM ROUTES
# ================================

@app.route('/api/final-exam/status', methods=['GET'])
@jwt_required()
def get_final_exam_status():
    """Check if final exam is unlocked and if it has been taken"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        
        # Get active syllabus
        syllabus = Syllabus.query.filter_by(user_id=user_id).order_by(Syllabus.last_accessed.desc()).first()
        if not syllabus:
            return jsonify({
                'unlocked': False,
                'alreadyTaken': False,
                'score': None,
                'message': 'No syllabus found'
            }), 200

        # Calculate if all topics are verified for THIS syllabus
        total_topics = Topic.query.join(Subject).filter(Subject.syllabus_id == syllabus.id).count()
        verified_topics = Topic.query.join(Subject).filter(
            Subject.syllabus_id == syllabus.id,
            Topic.status == 'verified'
        ).count()
        
        unlocked = total_topics > 0 and total_topics == verified_topics
        
        # Check if exam already taken for THIS syllabus
        final_exam = FinalExam.query.filter_by(user_id=user_id, syllabus_id=syllabus.id).first()
        
        return jsonify({
            'unlocked': unlocked,
            'alreadyTaken': final_exam.completed if final_exam else False,
            'score': final_exam.score if final_exam and final_exam.completed else None
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/final-exam/questions', methods=['GET'])
@jwt_required()
def get_final_exam_questions():
    """Get final exam questions"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        
        # Get all verified topics
        syllabus = Syllabus.query.filter_by(user_id=user_id).order_by(Syllabus.last_accessed.desc()).first()
        
        if not syllabus:
            return jsonify({'error': 'No syllabus found'}), 404
        
        # Get questions from all topics
        questions = []
        topics = Topic.query.join(Subject).filter(
            Subject.syllabus_id == syllabus.id,
            Topic.status == 'verified'
        ).all()
        
        for topic in topics:
            topic_questions = Question.query.filter_by(topic_id=topic.id).limit(1).all()
            questions.extend([q.to_dict(include_answer=False) for q in topic_questions])
        
        # Limit to 50 questions
        questions = questions[:50]
        
        return jsonify({'questions': questions}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/final-exam/submit', methods=['POST'])
@jwt_required()
def submit_final_exam():
    """Submit final exam"""
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User session invalid. Please log out and log in again."}), 401
        data = request.get_json()
        
        # Get active syllabus
        syllabus = Syllabus.query.filter_by(user_id=user_id).order_by(Syllabus.last_accessed.desc()).first()
        if not syllabus:
            return jsonify({'error': 'No active syllabus found'}), 404

        answers = data.get('answers', [])
        
        # For demo purposes, generate a random score
        score = random.randint(60, 95)
        
        # Save or update final exam record for this specific syllabus
        final_exam = FinalExam.query.filter_by(user_id=user_id, syllabus_id=syllabus.id).first()
        
        if final_exam:
            final_exam.score = score
            final_exam.completed = True
            final_exam.completed_at = datetime.utcnow()
        else:
            final_exam = FinalExam(
                user_id=user_id,
                syllabus_id=syllabus.id,
                score=score,
                completed=True,
                completed_at=datetime.utcnow()
            )
            db.session.add(final_exam)
        
        db.session.commit()
        
        return jsonify({
            'score': score,
            'passed': score >= 60
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ================================
# ADMIN ROUTES
# ================================

@app.route('/api/admin/users', methods=['GET'])
@jwt_required()
def get_all_users():
    """Get all users (admin only)"""
    try:
        user_id = get_jwt_identity()
        current_user = User.query.get(user_id)
        
        if not current_user or current_user.role != 'admin':
            return jsonify({'error': 'Unauthorized'}), 403
        
        users = User.query.all()
        
        users_data = []
        for user in users:
            user_dict = user.to_dict()
            
            # Calculate progress
            syllabus = Syllabus.query.filter_by(user_id=user.id).order_by(Syllabus.last_accessed.desc()).first()
            if syllabus:
                total_topics = Topic.query.join(Subject).filter(Subject.syllabus_id == syllabus.id).count()
                verified_topics = Topic.query.join(Subject).filter(
                    Subject.syllabus_id == syllabus.id,
                    Topic.status == 'verified'
                ).count()
                user_dict['progress'] = int((verified_topics / total_topics) * 100) if total_topics > 0 else 0
            else:
                user_dict['progress'] = 0
            
            users_data.append(user_dict)
        
        return jsonify({'users': users_data}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@jwt_required()
def delete_user(user_id):
    """Delete a user (admin only)"""
    try:
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        
        if not current_user or current_user.role != 'admin':
            return jsonify({'error': 'Unauthorized'}), 403
        
        if current_user_id == user_id:
            return jsonify({'error': 'Cannot delete yourself'}), 400
        
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        db.session.delete(user)
        db.session.commit()
        
        return jsonify({'message': 'User deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ================================
# SETTINGS ROUTES
# ================================

@app.route('/api/settings/profile', methods=['PUT', 'OPTIONS'], strict_slashes=False)
@jwt_required(optional=True)
def update_profile():
    """Update user profile"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    try:
        from flask_jwt_extended import verify_jwt_in_request
        verify_jwt_in_request()
        user_id = get_jwt_identity()
        data = request.get_json()
        
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if 'name' in data:
            user.name = data['name']
        
        if 'email' in data:
            # Check if email already exists
            existing = User.query.filter(User.email == data['email'], User.id != user_id).first()
            if existing:
                return jsonify({'error': 'Email already in use'}), 400
            user.email = data['email']
        
        db.session.commit()
        
        return jsonify({
            'message': 'Profile updated successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/password', methods=['PUT', 'OPTIONS'], strict_slashes=False)
@jwt_required(optional=True)
def change_password():
    """Change user password"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    try:
        from flask_jwt_extended import verify_jwt_in_request
        verify_jwt_in_request()
        user_id = get_jwt_identity()
        data = request.get_json()
        
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if not data.get('currentPassword') or not data.get('newPassword'):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Verify current password
        if not bcrypt.check_password_hash(user.password, data['currentPassword']):
            return jsonify({'error': 'Current password is incorrect'}), 401
        
        # Update password
        user.password = bcrypt.generate_password_hash(data['newPassword']).decode('utf-8')
        db.session.commit()
        
        return jsonify({'message': 'Password changed successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ================================
# ERROR HANDLERS
# ================================

@app.errorhandler(404)
def not_found(e):
    p = request.path or ''
    if p.startswith('/api'):
        return jsonify({'error': 'Resource not found'}), 404
    return redirect('http://localhost:8000/landing/home.html', code=302)


@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error'}), 500


# ================================
# INITIALIZE DATABASE
# ================================

def init_db():
    """Initialize database with tables"""
    try:
        with app.app_context():
            db.create_all()
            
            # Create admin user if not exists
            admin = User.query.filter_by(email='admin@studymap.com').first()
            if not admin:
                admin = User(
                    name='Admin User',
                    email='admin@studymap.com',
                    password=bcrypt.generate_password_hash('admin123').decode('utf-8'),
                    role='admin'
                )
                db.session.add(admin)
                db.session.flush()  # Flush to generate user ID
                
                # Create streak for admin
                streak = Streak(
                    user_id=admin.id,
                    current_streak=0,
                    longest_streak=0,
                    activity_dates='[]'
                )
                db.session.add(streak)
                
                db.session.commit()
                print('✅ Admin user created: admin@studymap.com / admin123')
            else:
                print('✅ Admin user already exists')
    except Exception as e:
        print(f"⚠️  Database initialization warning: {str(e)}")
        print("   The server will continue, but API may not work until database is available")
        print("   Make sure MySQL is running and credentials in .env are correct")


# ================================
# RUN APPLICATION
# ================================

if __name__ == '__main__':
    init_db()
    print('✅ Database initialized')
    print('🚀 Starting Flask server on http://localhost:5000')
    app.run(debug=True, host='0.0.0.0', port=5000)
