from flask import Flask, request, jsonify
from datetime import datetime
import mysql.connector
from mysql.connector import Error
import os
import time
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import Gauge

app = Flask(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter('flask_request_count', 'Total number of HTTP requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('flask_request_latency_seconds', 'Request latency in seconds', ['method', 'endpoint'])
TODO_COUNT = Gauge('todo_items_total', 'Total number of todo items in database')

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
    connection = get_db_connection(with_database=False)
    if not connection:
        print("Failed to connect to MariaDB server")
        return False
    
    try:
        cursor = connection.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
        connection.commit()
        
        cursor.execute(f"USE {DB_CONFIG['database']}")
        
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

def update_todo_count():
    """Update the total todo items count metric"""
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM todos")
            count = cursor.fetchone()[0]
            TODO_COUNT.set(count)
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
    start_time = time.time()
    if not ensure_db_initialized():
        REQUEST_COUNT.labels('GET', '/todos', '500').inc()
        latency = time.time() - start_time
        REQUEST_LATENCY.labels('GET', '/todos').observe(latency)
        return jsonify({'error': 'Database initialization failed'}), 500
    
    connection = get_db_connection()
    if not connection:
        REQUEST_COUNT.labels('GET', '/todos', '500').inc()
        latency = time.time() - start_time
        REQUEST_LATENCY.labels('GET', '/todos').observe(latency)
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id, title, created_at FROM todos")
        todos = cursor.fetchall()
        for todo in todos:
            todo['created_at'] = todo['created_at'].isoformat()
        update_todo_count()
        REQUEST_COUNT.labels('GET', '/todos', '200').inc()
        latency = time.time() - start_time
        REQUEST_LATENCY.labels('GET', '/todos').observe(latency)
        return jsonify(todos), 200
    except Error as e:
        REQUEST_COUNT.labels('GET', '/todos', '500').inc()
        latency = time.time() - start_time
        REQUEST_LATENCY.labels('GET', '/todos').observe(latency)
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        connection.close()

@app.route('/todos', methods=['POST'])
def add_todo():
    """Add a new todo item."""
    start_time = time.time()
    if not ensure_db_initialized():
        REQUEST_COUNT.labels('POST', '/todos', '500').inc()
        latency = time.time() - start_time
        REQUEST_LATENCY.labels('POST', '/todos').observe(latency)
        return jsonify({'error': 'Database initialization failed'}), 500
    
    data = request.get_json()
    if not data or 'title' not in data or not data['title']:
        REQUEST_COUNT.labels('POST', '/todos', '400').inc()
        latency = time.time() - start_time
        REQUEST_LATENCY.labels('POST', '/todos').observe(latency)
        return jsonify({'error': 'Title is required'}), 400
    
    connection = get_db_connection()
    if not connection:
        REQUEST_COUNT.labels('POST', '/todos', '500').inc()
        latency = time.time() - start_time
        REQUEST_LATENCY.labels('POST', '/todos').observe(latency)
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
        update_todo_count()
        REQUEST_COUNT.labels('POST', '/todos', '201').inc()
        latency = time.time() - start_time
        REQUEST_LATENCY.labels('POST', '/todos').observe(latency)
        return jsonify(todo_dict), 201
    except Error as e:
        REQUEST_COUNT.labels('POST', '/todos', '500').inc()
        latency = time.time() - start_time
        REQUEST_LATENCY.labels('POST', '/todos').observe(latency)
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        connection.close()

@app.route('/metrics')
def metrics():
    """Expose Prometheus metrics."""
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}

if __name__ == '__main__':
    if not init_db():
        print("Initial database setup failed, will retry on first request")
    app.run(debug=True, host='0.0.0.0', port=5000)