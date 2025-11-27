"""
Waitlist API for Email Bot Integration

This Flask API provides endpoints for the email bot to:
1. Add customers to the waitlist (opt-in)
2. Check waitlist status
3. Update waitlist entries

Run with: gunicorn api:app --bind 0.0.0.0:5000
"""

from flask import Flask, request, jsonify
from functools import wraps
import psycopg
from psycopg.rows import dict_row
import os
from datetime import datetime

app = Flask(__name__)

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
API_SECRET_KEY = os.getenv("WAITLIST_API_KEY", "your-secret-key-here")  # Set this in environment


def get_db_connection():
    """Get database connection"""
    return psycopg.connect(DATABASE_URL)


def require_api_key(f):
    """Decorator to require API key for endpoints"""
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.headers.get('Authorization', '').replace('Bearer ', '')
        if api_key != API_SECRET_KEY:
            return jsonify({'error': 'Invalid or missing API key'}), 401
        return f(*args, **kwargs)
    return decorated


def create_waitlist_table_if_not_exists():
    """Ensure waitlist table exists"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS waitlist (
                id SERIAL PRIMARY KEY,
                waitlist_id VARCHAR(50) UNIQUE NOT NULL,
                guest_email VARCHAR(255) NOT NULL,
                guest_name VARCHAR(255),
                requested_date DATE NOT NULL,
                preferred_time VARCHAR(50),
                time_flexibility VARCHAR(50) DEFAULT 'Flexible',
                players INTEGER DEFAULT 1,
                golf_course VARCHAR(255),
                status VARCHAR(50) DEFAULT 'Waiting',
                priority INTEGER DEFAULT 5,
                notes TEXT,
                notification_sent BOOLEAN DEFAULT FALSE,
                notification_sent_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                club VARCHAR(100) NOT NULL,
                source VARCHAR(50) DEFAULT 'manual',
                opt_in_confirmed BOOLEAN DEFAULT FALSE,
                original_booking_request TEXT
            );
        """)
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error creating waitlist table: {e}")
        return False


# ========================================
# API ENDPOINTS FOR EMAIL BOT
# ========================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})


@app.route('/api/waitlist/add', methods=['POST'])
@require_api_key
def add_to_waitlist():
    """
    Add a customer to the waitlist (called by email bot when customer opts in)

    Expected JSON payload:
    {
        "guest_email": "customer@example.com",
        "guest_name": "John Doe",
        "requested_date": "2024-03-15",
        "preferred_time": "10:00 AM",
        "time_flexibility": "Flexible",  // "Flexible", "Morning Only", "Afternoon Only", "Exact Time"
        "players": 4,
        "golf_course": "The Island Golf Club",
        "club": "island",
        "notes": "Original request details...",
        "priority": 5,  // 1-10
        "opt_in_confirmed": true,
        "original_booking_request": "Full email content or booking details"
    }
    """
    create_waitlist_table_if_not_exists()

    try:
        data = request.get_json()

        # Validate required fields
        required_fields = ['guest_email', 'requested_date', 'club']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Missing required field: {field}'}), 400

        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        # Check if customer is already on waitlist for this date
        cursor.execute("""
            SELECT waitlist_id, status FROM waitlist
            WHERE guest_email = %s AND requested_date = %s AND club = %s
            AND status IN ('Waiting', 'Notified')
        """, (data['guest_email'], data['requested_date'], data['club']))

        existing = cursor.fetchone()
        if existing:
            cursor.close()
            conn.close()
            return jsonify({
                'success': False,
                'message': 'Customer already on waitlist for this date',
                'waitlist_id': existing['waitlist_id'],
                'status': existing['status']
            }), 409

        # Generate waitlist ID
        waitlist_id = f"WL-{datetime.now().strftime('%Y%m%d%H%M%S')}-{hash(data['guest_email']) % 10000:04d}"

        # Insert into waitlist
        cursor.execute("""
            INSERT INTO waitlist (
                waitlist_id, guest_email, guest_name, requested_date, preferred_time,
                time_flexibility, players, golf_course, notes, club, priority,
                source, opt_in_confirmed, original_booking_request
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, waitlist_id, created_at
        """, (
            waitlist_id,
            data['guest_email'],
            data.get('guest_name', ''),
            data['requested_date'],
            data.get('preferred_time', 'Flexible'),
            data.get('time_flexibility', 'Flexible'),
            data.get('players', 1),
            data.get('golf_course', ''),
            data.get('notes', ''),
            data['club'],
            data.get('priority', 5),
            'email_bot',  # Mark source as email bot
            data.get('opt_in_confirmed', True),
            data.get('original_booking_request', '')
        ))

        result = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': 'Customer added to waitlist',
            'waitlist_id': result['waitlist_id'],
            'created_at': result['created_at'].isoformat()
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/waitlist/check', methods=['GET'])
@require_api_key
def check_waitlist_status():
    """
    Check if a customer is on the waitlist

    Query parameters:
    - email: Customer email address
    - date: Requested date (optional)
    - club: Club ID
    """
    create_waitlist_table_if_not_exists()

    try:
        email = request.args.get('email')
        date = request.args.get('date')
        club = request.args.get('club')

        if not email or not club:
            return jsonify({'error': 'Missing required parameters: email and club'}), 400

        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        if date:
            cursor.execute("""
                SELECT waitlist_id, guest_email, guest_name, requested_date, preferred_time,
                       status, priority, created_at, notification_sent
                FROM waitlist
                WHERE guest_email = %s AND requested_date = %s AND club = %s
                ORDER BY created_at DESC
            """, (email, date, club))
        else:
            cursor.execute("""
                SELECT waitlist_id, guest_email, guest_name, requested_date, preferred_time,
                       status, priority, created_at, notification_sent
                FROM waitlist
                WHERE guest_email = %s AND club = %s
                ORDER BY requested_date ASC, created_at DESC
            """, (email, club))

        entries = cursor.fetchall()
        cursor.close()
        conn.close()

        # Convert to serializable format
        result = []
        for entry in entries:
            result.append({
                'waitlist_id': entry['waitlist_id'],
                'guest_email': entry['guest_email'],
                'guest_name': entry['guest_name'],
                'requested_date': entry['requested_date'].isoformat() if entry['requested_date'] else None,
                'preferred_time': entry['preferred_time'],
                'status': entry['status'],
                'priority': entry['priority'],
                'created_at': entry['created_at'].isoformat() if entry['created_at'] else None,
                'notification_sent': entry['notification_sent']
            })

        return jsonify({
            'on_waitlist': len(result) > 0,
            'count': len(result),
            'entries': result
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/waitlist/update/<waitlist_id>', methods=['PATCH'])
@require_api_key
def update_waitlist_entry(waitlist_id):
    """
    Update a waitlist entry status

    Expected JSON payload:
    {
        "status": "Notified",  // "Waiting", "Notified", "Converted", "Expired", "Cancelled"
        "notification_sent": true,
        "notes": "Additional notes..."
    }
    """
    try:
        data = request.get_json()

        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        # Build update query dynamically
        updates = []
        values = []

        if 'status' in data:
            updates.append("status = %s")
            values.append(data['status'])

        if 'notification_sent' in data:
            updates.append("notification_sent = %s")
            values.append(data['notification_sent'])
            if data['notification_sent']:
                updates.append("notification_sent_at = NOW()")

        if 'notes' in data:
            updates.append("notes = %s")
            values.append(data['notes'])

        if 'priority' in data:
            updates.append("priority = %s")
            values.append(data['priority'])

        if not updates:
            return jsonify({'error': 'No valid fields to update'}), 400

        updates.append("updated_at = NOW()")
        values.append(waitlist_id)

        query = f"UPDATE waitlist SET {', '.join(updates)} WHERE waitlist_id = %s RETURNING *"
        cursor.execute(query, values)

        result = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        if not result:
            return jsonify({'error': 'Waitlist entry not found'}), 404

        return jsonify({
            'success': True,
            'message': 'Waitlist entry updated',
            'waitlist_id': result['waitlist_id'],
            'status': result['status']
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/waitlist/matches', methods=['GET'])
@require_api_key
def get_waitlist_matches():
    """
    Get waitlist entries matching an available date/time
    (Call this when a tee time becomes available)

    Query parameters:
    - date: Available date
    - club: Club ID
    - time: Available time (optional)
    """
    create_waitlist_table_if_not_exists()

    try:
        date = request.args.get('date')
        club = request.args.get('club')
        time = request.args.get('time')

        if not date or not club:
            return jsonify({'error': 'Missing required parameters: date and club'}), 400

        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        cursor.execute("""
            SELECT waitlist_id, guest_email, guest_name, requested_date, preferred_time,
                   time_flexibility, players, golf_course, priority, notes
            FROM waitlist
            WHERE club = %s AND requested_date = %s AND status = 'Waiting'
            ORDER BY priority DESC, created_at ASC
        """, (club, date))

        matches = cursor.fetchall()
        cursor.close()
        conn.close()

        # Convert to serializable format
        result = []
        for match in matches:
            result.append({
                'waitlist_id': match['waitlist_id'],
                'guest_email': match['guest_email'],
                'guest_name': match['guest_name'],
                'requested_date': match['requested_date'].isoformat() if match['requested_date'] else None,
                'preferred_time': match['preferred_time'],
                'time_flexibility': match['time_flexibility'],
                'players': match['players'],
                'golf_course': match['golf_course'],
                'priority': match['priority'],
                'notes': match['notes']
            })

        return jsonify({
            'available_date': date,
            'available_time': time,
            'matches_found': len(result),
            'matches': result
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/waitlist/remove/<waitlist_id>', methods=['DELETE'])
@require_api_key
def remove_from_waitlist(waitlist_id):
    """Remove a customer from the waitlist"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM waitlist WHERE waitlist_id = %s RETURNING waitlist_id", (waitlist_id,))
        result = cursor.fetchone()

        conn.commit()
        cursor.close()
        conn.close()

        if not result:
            return jsonify({'error': 'Waitlist entry not found'}), 404

        return jsonify({
            'success': True,
            'message': 'Waitlist entry removed',
            'waitlist_id': waitlist_id
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    create_waitlist_table_if_not_exists()
    app.run(debug=True, host='0.0.0.0', port=5000)
