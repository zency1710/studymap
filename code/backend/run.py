"""
StudyMap Backend Server
Run this script to start the Flask development server
"""

import os
import sys
import subprocess
import time
from urllib.parse import urlparse, unquote
import mysql.connector

def check_dependencies():
    """Check if all required packages are installed"""
    required = [
        'flask',
        'flask_cors',
        'flask_sqlalchemy',
        'flask_bcrypt',
        'flask_jwt_extended',
        'PyPDF2',
        'pdfplumber',
        'mysql.connector',
        'dotenv',
        'openai'
    ]
    
    missing = []
    for package in required:
        try:
            __import__(package)
        except ImportError:
            missing.append(package)
    
    if missing:
        print("❌ Missing required packages:")
        for pkg in missing:
            print(f"   - {pkg}")
        print("\n📦 Install missing packages with:")
        print("   pip install -r requirements.txt")
        return False
    
    return True


def create_upload_folder():
    """Create upload folder if it doesn't exist"""
    upload_folder = 'uploads'
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
        print(f"✅ Created upload folder: {upload_folder}")

def ensure_mysql_database():
    """Ensure MySQL database exists and is accessible"""
    dsn = os.environ.get('DATABASE_URL') or 'mysql+mysqlconnector://root:root123@localhost/studymap'
    parsed = urlparse(dsn)
    user = parsed.username or 'root'
    password = unquote(parsed.password or '')
    host = parsed.hostname or 'localhost'
    port = parsed.port or 3306
    db_name = (parsed.path or '/studymap').lstrip('/') or 'studymap'
    
    # Try to connect with provided credentials
    try:
        conn = mysql.connector.connect(host=host, user=user, password=password, port=port)
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ Ensured MySQL database exists: {db_name}")
    except Exception as e:
        print(f"⚠️  MySQL connection failed: {str(e)}")
        print("💡 Make sure MySQL server is running and credentials are correct.")
        print(f"   Database URL: {dsn.replace(password, '****')}")
        print("\n🔑 Please ensure MySQL is installed and running, then try again.")
        # Don't exit - let Flask handle the database connection error gracefully

import webbrowser

def start_frontend_server():
    here = os.path.dirname(os.path.abspath(__file__))
    # Robustly find frontend directory (handling different nesting levels)
    potential_paths = [
        os.path.join(here, '..', 'frontend'),
        os.path.join(here, '..', '..', 'frontend'),
        os.path.join(here, 'code', 'frontend')
    ]
    
    frontend_dir = None
    for path in potential_paths:
        norm_path = os.path.normpath(path)
        if os.path.exists(norm_path) and os.path.isdir(norm_path):
            frontend_dir = norm_path
            break
    
    if not frontend_dir:
        print("❌ Could not locate 'frontend' directory.")
        print(f"   Checked paths relative to {here}:")
        for p in potential_paths:
            print(f"   - {os.path.normpath(p)}")
        sys.exit(1)

    try:
        proc = subprocess.Popen([sys.executable, "-m", "http.server", "8000"], cwd=frontend_dir)
        time.sleep(1)
        print("🚀 Starting Frontend server...")
        print("📍 Frontend running at: http://localhost:8000")
        
        # Open browser
        try:
            webbrowser.open('http://localhost:8000')
            print("🌐 Opened in default browser")
        except Exception:
            pass
            
        return proc
    except Exception as e:
        print(f"❌ Error starting frontend server: {str(e)}")
        sys.exit(1)

def main():
    """Main function to run the server"""
    print("=" * 60)
    print("StudyMap Backend Server")
    print("=" * 60)
    print()
    
    # Check dependencies
    print("🔍 Checking dependencies...")
    if not check_dependencies():
        sys.exit(1)
    print("✅ All dependencies installed")
    print()
    
    # Ensure MySQL database is ready and environment is set
    ensure_mysql_database()
    print()
    
    # Create upload folder
    create_upload_folder()
    print()
    
    # Import and run the app
    try:
        fe_proc = start_frontend_server()
        from app import app, init_db
        
        print("🗄️  Initializing database...")
        init_db()
        print()
        
        print("🚀 Starting Flask server...")
        print("📍 Server running at: http://localhost:5000")
        print("📍 API base URL: http://localhost:5000/api")
        print("📍 Frontend URL: http://localhost:8000")
        print()
        print("📝 Default admin credentials:")
        print("   Email: admin@studymap.com")
        print("   Password: admin123")
        print()
        print("Press CTRL+C to stop the server")
        print("=" * 60)
        print()
        
        app.run(debug=True, host='0.0.0.0', port=5000)
        
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped")
    except Exception as e:
        print(f"\n❌ Error starting server: {str(e)}")
        sys.exit(1)
    finally:
        try:
            if 'fe_proc' in locals() and fe_proc and fe_proc.poll() is None:
                fe_proc.terminate()
        except Exception:
            pass


if __name__ == '__main__':
    main()
