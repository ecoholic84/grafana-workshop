from flask import Flask, request, jsonify
from datetime import datetime
import mysql.connector
from mysql.connector import Error
import os
import time

app = Flask(__name__)

# Database configuration from environment variables
DB_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'user': os.getenv('MYSQL_USER', 'todo_user'),
    'password': os.getenv('MYSQL_PASSWORD', 'your_secure_password'),
    'database': os.getenv('MYSQL_DATABASE', 'todo_db')
}

def get_db_connection(with_database=True, retries=5, delay=2):
    """Create a database connection with retry logic."""
    config = DB_CONFIG.copy()
    if not with_database:
        del config['database']
    
    for attempt in range(retries):
        try:
            connection = mysql.connector.connect(**config)
            return connection
        except Error as e:
            print(f"Connection attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    print("Failed to connect to MariaDB after retries")
    return None

def init_db():
    """Initialize the database and todos table if they don't exist."""
    # Connect to server without database
    connection = get_db_connection(with_database=False)
    if not connection:
        print("Failed to connect to MariaDB server")
        return False
    
    try:
        cursor = connection.cursor()
        # Create database
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
        connection.commit()
        
        # Switch to database
        cursor.execute(f"USE {DB_CONFIG['database']}")
        
        # Create table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS todos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.commit()
        print("Database and table initialized successfully")
        return True
    except Error as e:
        print(f"Error initializing database: {e}")
        return False
    finally:
        cursor.close()
        connection.close()

def ensure_db_initialized():
    """Ensure database is initialized before handling requests."""
    connection = get_db_connection()
    if not connection:
        print("Attempting to initialize database due to connection failure")
        init_db()
        return False
    
    try:
        cursor = connection.cursor()
        cursor.execute("SHOW TABLES LIKE 'todos'")
        if not cursor.fetchone():
            print("Table 'todos' not found, initializing database")
            connection.close()
            return init_db()
        return True
    except Error as e:
        print(f"Error checking table existence: {e}")
        return False
    finally:
        if connection.is_connected():
            connection.close()

@app.route('/todos', methods=['GET'])
def list_todos():
    """Retrieve all todo items."""
    if not ensure_db_initialized():
        return jsonify({'error': 'Database initialization failed'}), 500
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id, title, created_at FROM todos")
        todos = cursor.fetchall()
        for todo in todos:
            todo['created_at'] = todo['created_at'].isoformat()
        return jsonify(todos), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        connection.close()

@app.route('/todos', methods=['POST'])
def add_todo():
    """Add a new todo item."""
    if not ensure_db_initialized():
        return jsonify({'error': 'Database initialization failed'}), 500
    
    data = request.get_json()
    if not data or 'title' not in data or not data['title']:
        return jsonify({'error': 'Title is required'}), 400
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cursor = connection.cursor()
        query = "INSERT INTO todos (title) VALUES (%s)"
        cursor.execute(query, (data['title'],))
        connection.commit()
        
        new_id = cursor.lastrowid
        cursor.execute("SELECT id, title, created_at FROM todos WHERE id = %s", (new_id,))
        new_todo = cursor.fetchone()
        todo_dict = {
            'id': new_todo[0],
            'title': new_todo[1],
            'created_at': new_todo[2].isoformat()
        }
        return jsonify(todo_dict), 201
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        connection.close()

if __name__ == '__main__':
    # Initial database setup
    if not init_db():
        print("Initial database setup failed, will retry on first request")
    app.run(debug=True, host='0.0.0.0', port=5000)