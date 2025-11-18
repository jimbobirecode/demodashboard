import streamlit as st
import pandas as pd
import os
import bcrypt
import psycopg
from psycopg.rows import dict_row
from datetime import datetime, timedelta
from io import BytesIO
import html
import re

# ========================================
# DATABASE CONNECTION
# ========================================
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    """Get database connection"""
    return psycopg.connect(DATABASE_URL)

def extract_tee_time_from_note(note_content):
    """
    Extract tee time from email content.
    Looks for patterns like:
    - Time: 12:20 PM
    - Time: 10:30 AM
    - Tee Time: 3:45 PM
    """
    if not note_content or pd.isna(note_content):
        return None

    # Pattern to match "Time: HH:MM AM/PM"
    patterns = [
        r'Time:\s*(\d{1,2}:\d{2}\s*[AaPp][Mm])',  # Time: 12:20 PM
        r'time:\s*(\d{1,2}:\d{2}\s*[AaPp][Mm])',  # time: 12:20 pm (case insensitive)
        r'Tee\s+Time:\s*(\d{1,2}:\d{2}\s*[AaPp][Mm])',  # Tee Time: 12:20 PM
    ]

    for pattern in patterns:
        match = re.search(pattern, str(note_content), re.IGNORECASE)
        if match:
            tee_time = match.group(1).strip()
            # Normalize to uppercase (12:20 PM)
            return tee_time.upper()

    return None

def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash"""
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

def authenticate_user(username: str, password: str):
    """Authenticate user - handles both temp passwords and set passwords
    Returns (success, customer_id, full_name, must_change_password, user_id)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)
        cursor.execute("""
            SELECT id, password_hash, temp_password, customer_id, full_name,
                   is_active, must_change_password
            FROM dashboard_users
            WHERE username = %s;
        """, (username,))
        
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            conn.close()
            return False, None, None, False, None
        
        if not user['is_active']:
            cursor.close()
            conn.close()
            return False, None, None, False, None
        
        # Check if using temporary password (first login)
        if user['must_change_password'] and user['temp_password']:
            if password == user['temp_password']:
                cursor.close()
                conn.close()
                return True, user['customer_id'], user['full_name'], True, user['id']
        
        # Check regular password
        if user['password_hash'] and verify_password(password, user['password_hash']):
            cursor.close()
            conn.close()
            return True, user['customer_id'], user['full_name'], False, user['id']
        
        cursor.close()
        conn.close()
        return False, None, None, False, None
    except Exception as e:
        st.error(f"Authentication error: {e}")
        return False, None, None, False, None


def set_permanent_password(user_id: int, new_password: str):
    """Set permanent password and clear temp password"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        password_hash = hash_password(new_password)
        
        cursor.execute("""
            UPDATE dashboard_users
            SET password_hash = %s,
                temp_password = NULL,
                must_change_password = FALSE,
                last_login = NOW()
            WHERE id = %s;
        """, (password_hash, user_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error setting password: {e}")
        return False


def update_last_login(user_id: int):
    """Update last login timestamp"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE dashboard_users SET last_login = NOW() WHERE id = %s;", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        st.error(f"Error updating last login: {e}")


# ========================================
# BOOKING STATUS HELPERS
# ========================================
def get_status_icon(status: str) -> str:
    """Get timeline icon for booking status"""
    status_icons = {
        'Inquiry': '🔵',
        'Requested': '🟡',
        'Confirmed': '🟠',
        'Booked': '✅',
        'Rejected': '❌',
        'Cancelled': '⚫',
        'Pending': '🟡',
    }
    return status_icons.get(status, '⚪')


def get_status_color(status: str) -> str:
    """Get color class for status badge"""
    status_map = {
        'Inquiry': 'status-inquiry',
        'Requested': 'status-requested',
        'Confirmed': 'status-confirmed',
        'Booked': 'status-booked',
        'Rejected': 'status-rejected',
        'Cancelled': 'status-cancelled',
        'Pending': 'status-requested',
    }
    return status_map.get(status, 'status-inquiry')


def generate_status_progress_bar(current_status: str) -> str:
    """Generate a linear status progress bar showing booking workflow"""

    # Define the workflow stages
    stages = [
        {'name': 'Inquiry', 'color': '#60a5fa'},
        {'name': 'Requested', 'color': '#eab308'},
        {'name': 'Confirmed', 'color': '#f97316'},
        {'name': 'Booked', 'color': '#10b981'}
    ]

    # Handle special cases
    if current_status == 'Pending':
        current_status = 'Inquiry'

    # Check if rejected or cancelled
    is_rejected = current_status == 'Rejected'
    is_cancelled = current_status == 'Cancelled'

    if is_rejected or is_cancelled:
        status_color = '#ef4444' if is_rejected else '#64748b'
        return f"""
        <div style='background: #0a0f1e; padding: 1rem; border-radius: 8px; border: 1px solid #1e293b;'>
            <div style='display: flex; align-items: center; justify-content: center; gap: 0.75rem;'>
                <div style='width: 12px; height: 12px; border-radius: 50%; background: {status_color};'></div>
                <span style='color: {status_color}; font-weight: 700; font-size: 1rem; text-transform: uppercase; letter-spacing: 0.5px;'>{current_status}</span>
            </div>
        </div>
        """

    # Find current stage index
    current_index = next((i for i, s in enumerate(stages) if s['name'] == current_status), 0)

    # Generate HTML
    html = """
    <div style='background: #0a0f1e; padding: 1.25rem; border-radius: 8px; border: 1px solid #1e293b;'>
        <div style='display: flex; align-items: center; justify-content: space-between; position: relative;'>
    """

    # Add connecting line
    html += """
        <div style='position: absolute; top: 1rem; left: 2rem; right: 2rem; height: 3px; background: #1e293b; z-index: 1;'></div>
    """

    # Add progress line (only up to current stage)
    progress_width = (current_index / (len(stages) - 1)) * 100 if len(stages) > 1 else 0
    html += f"""
        <div style='position: absolute; top: 1rem; left: 2rem; width: calc({progress_width}% - 2rem); height: 3px; background: linear-gradient(90deg, #60a5fa, #10b981); z-index: 2;'></div>
    """

    # Add stage nodes
    for i, stage in enumerate(stages):
        is_active = i <= current_index
        is_current = i == current_index

        bg_color = stage['color'] if is_active else '#1e293b'
        text_color = '#f9fafb' if is_active else '#64748b'
        border_color = stage['color'] if is_current else ('#2d3748' if is_active else '#1e293b')

        html += f"""
        <div style='display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative;'>
            <div style='
                width: 1.5rem;
                height: 1.5rem;
                border-radius: 50%;
                background: {bg_color};
                border: 3px solid {border_color};
                box-shadow: {('0 0 0 4px rgba(16, 185, 129, 0.2)' if is_current else 'none')};
                transition: all 0.3s ease;
            '>
            </div>
            <div style='
                margin-top: 0.5rem;
                font-size: 0.7rem;
                font-weight: {('700' if is_current else '600')};
                color: {text_color};
                text-transform: uppercase;
                letter-spacing: 0.5px;
                white-space: nowrap;
            '>{stage['name']}</div>
        </div>
        """

    html += """
        </div>
    </div>
    """

    return html


# ========================================
# SESSION STATE
# ========================================
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'customer_id' not in st.session_state:
    st.session_state.customer_id = None
if 'username' not in st.session_state:
    st.session_state.username = None
if 'full_name' not in st.session_state:
    st.session_state.full_name = None
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'must_change_password' not in st.session_state:
    st.session_state.must_change_password = False
if 'show_password_change' not in st.session_state:
    st.session_state.show_password_change = False


# ========================================
# LOGOUT FUNCTION
# ========================================
def logout():
    st.session_state.authenticated = False
    st.session_state.customer_id = None
    st.session_state.username = None
    st.session_state.full_name = None
    st.session_state.user_id = None
    st.session_state.must_change_password = False
    st.session_state.show_password_change = False


# ========================================
# STREAMLIT PAGE CONFIG
# ========================================
st.set_page_config(
    page_title="TeeMail Dashboard",
    page_icon="🏌️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========================================
# STYLING - ENTERPRISE GRADE
# ========================================
st.markdown("""
    <style>
    .main {
        background: #0a0f1e;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
    }
    
    [data-testid="stSidebar"] {
        background: #0f1419;
        border-right: 1px solid #1e293b;
    }
    
    .metric-card {
        background: linear-gradient(135deg, #141b2b 0%, #1a2332 100%);
        padding: 1.75rem;
        border-radius: 12px;
        border: 1px solid #1e293b;
        transition: all 0.3s ease;
        position: relative;
        overflow: hidden;
    }

    .metric-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: linear-gradient(90deg, #60a5fa, #10b981);
        opacity: 0;
        transition: opacity 0.3s ease;
    }

    .metric-card:hover {
        border-color: #2d3748;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
        transform: translateY(-2px);
    }

    .metric-card:hover::before {
        opacity: 1;
    }
    
    .booking-id {
        font-size: 1rem;
        font-weight: 600;
        color: #f9fafb;
        margin: 0;
        font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
        letter-spacing: 0.5px;
    }
    
    .booking-email {
        color: #64748b;
        font-size: 0.875rem;
        margin: 0.375rem 0 0 0;
    }
    
    .timestamp {
        color: #64748b;
        font-size: 0.8125rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-weight: 500;
    }
    
    .timestamp-value {
        color: #94a3b8;
        font-size: 0.875rem;
        font-weight: 600;
        margin-top: 0.25rem;
    }
    
    .stTextArea textarea {
        background: #0a0f1e !important;
        border: 1px solid #1e293b !important;
        border-radius: 0 0 8px 8px !important;
        color: #cbd5e1 !important;
        font-family: 'SF Mono', 'Monaco', 'Consolas', monospace !important;
        font-size: 0.8125rem !important;
        line-height: 1.7 !important;
        padding: 1rem !important;
    }
    
    .stTextArea textarea:disabled {
        background: #0a0f1e !important;
        color: #cbd5e1 !important;
        opacity: 1 !important;
        -webkit-text-fill-color: #cbd5e1 !important;
    }
    
    .status-timeline {
        display: inline-flex;
        align-items: center;
        gap: 0.625rem;
        background: #0a0f1e;
        padding: 0.5rem 1rem;
        border-radius: 8px;
        border: 1px solid #1e293b;
    }
    
    .status-icon {
        font-size: 1.125rem;
        line-height: 1;
    }
    
    .status-badge {
        padding: 0.375rem 0.875rem;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.8125rem;
        display: inline-flex;
        align-items: center;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .status-inquiry {
        background: rgba(59, 130, 246, 0.1);
        color: #60a5fa;
        border: 1px solid rgba(59, 130, 246, 0.2);
    }

    .status-requested {
        background: rgba(234, 179, 8, 0.1);
        color: #eab308;
        border: 1px solid rgba(234, 179, 8, 0.2);
    }

    .status-confirmed {
        background: rgba(249, 115, 22, 0.1);
        color: #f97316;
        border: 1px solid rgba(249, 115, 22, 0.2);
    }

    .status-booked {
        background: rgba(16, 185, 129, 0.1);
        color: #10b981;
        border: 1px solid rgba(16, 185, 129, 0.2);
    }

    .status-rejected {
        background: rgba(239, 68, 68, 0.1);
        color: #ef4444;
        border: 1px solid rgba(239, 68, 68, 0.2);
    }

    .status-cancelled {
        background: rgba(100, 116, 139, 0.1);
        color: #64748b;
        border: 1px solid rgba(100, 116, 139, 0.2);
    }
    
    .stButton > button {
        background: #10b981;
        color: white;
        border: none;
        padding: 0.625rem 1.25rem;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.875rem;
        transition: all 0.2s ease;
        width: 100%;
        letter-spacing: 0.3px;
        cursor: pointer;
    }

    .stButton > button:hover {
        background: #059669;
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.25);
        transform: translateY(-1px);
    }

    .stButton > button:active {
        transform: translateY(0px);
    }
    
    h1 { 
        color: #f9fafb !important; 
        font-weight: 700 !important;
        font-size: 1.875rem !important;
        letter-spacing: -0.5px !important;
    }
    
    h2, h3, h4, h5, h6 { 
        color: #f9fafb !important; 
        font-weight: 600 !important; 
    }
    
    p, span, div, label { 
        color: #cbd5e1 !important; 
    }
    
    .user-badge {
        background: #10b981;
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 6px;
        font-size: 0.8125rem;
        font-weight: 600;
        display: inline-block;
        margin-bottom: 0.5rem;
        letter-spacing: 0.3px;
    }
    
    .club-badge {
        background: #eab308;
        color: #0f1419;
        padding: 0.5rem 1rem;
        border-radius: 6px;
        font-size: 0.8125rem;
        font-weight: 600;
        display: inline-block;
        margin-bottom: 1rem;
        letter-spacing: 0.3px;
    }
    
    .data-label {
        color: #64748b;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 0.5rem;
    }
    
    .streamlit-expanderHeader {
        background: #0f1419 !important;
        border-radius: 8px !important;
        border: 1px solid #1e293b !important;
        font-weight: 600 !important;
        font-size: 0.875rem !important;
        color: #cbd5e1 !important;
        transition: all 0.2s ease !important;
    }

    .streamlit-expanderHeader:hover {
        border-color: #2d3748 !important;
        background: #141b2b !important;
    }

    .streamlit-expanderContent {
        background: #0a0f1e !important;
        border: 1px solid #1e293b !important;
        border-top: none !important;
        border-radius: 0 0 8px 8px !important;
    }

    /* Card Animation */
    @keyframes slideUp {
        from {
            opacity: 0;
            transform: translateY(20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    .booking-card {
        animation: slideUp 0.3s ease-out;
    }
    
    .stMultiSelect > div > div {
        background: #141b2b !important;
        border: 1px solid #1e293b !important;
        border-radius: 6px !important;
    }
    
    .stDateInput > div > div {
        background: #141b2b !important;
        border: 1px solid #1e293b !important;
        border-radius: 6px !important;
    }
    
    #MainMenu {visibility: hidden;} 
    footer {visibility: hidden;} 
    header {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)


# ========================================
# PASSWORD CHANGE SCREEN
# ========================================
if st.session_state.show_password_change:
    st.markdown("""
        <style>
        .password-container {
            max-width: 500px;
            margin: 100px auto;
            padding: 2.5rem;
            background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
            border-radius: 16px;
            border: 1px solid rgba(16, 185, 129, 0.2);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        }
        .password-title {
            color: #f9fafb;
            font-size: 1.8rem;
            font-weight: 700;
            text-align: center;
            margin-bottom: 0.5rem;
        }
        .password-subtitle {
            color: #94a3b8;
            text-align: center;
            margin-bottom: 2rem;
            font-size: 0.95rem;
        }
        </style>
    """, unsafe_allow_html=True)
    
    st.markdown("""
        <div class="password-container">
            <div class="password-title">🔐 Set Your Password</div>
            <div class="password-subtitle">First-time setup - create your secure password</div>
        </div>
    """, unsafe_allow_html=True)
    
    with st.form("password_setup_form"):
        st.info(f"👋 Welcome, **{st.session_state.full_name}**! Please create a secure password for your account.")
        
        new_password = st.text_input("New Password", type="password", key="new_pass")
        confirm_password = st.text_input("Confirm Password", type="password", key="confirm_pass")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            submit = st.form_submit_button("✅ Set Password", use_container_width=True)
        with col2:
            cancel = st.form_submit_button("Cancel", use_container_width=True)
        
        if cancel:
            logout()
            st.rerun()
        
        if submit:
            if not new_password or not confirm_password:
                st.error("❌ Please fill in both password fields")
            elif new_password != confirm_password:
                st.error("❌ Passwords do not match")
            elif len(new_password) < 8:
                st.error("❌ Password must be at least 8 characters")
            else:
                if set_permanent_password(st.session_state.user_id, new_password):
                    update_last_login(st.session_state.user_id)
                    st.session_state.show_password_change = False
                    st.session_state.must_change_password = False
                    st.success("✅ Password set successfully!")
                    st.rerun()
                else:
                    st.error("❌ Error setting password. Please try again.")
    
    st.stop()


# ========================================
# LOGIN SCREEN
# ========================================
if not st.session_state.authenticated:
    st.markdown("""
        <style>
        .login-container {
            max-width: 450px;
            margin: 100px auto;
            padding: 2.5rem;
            background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
            border-radius: 16px;
            border: 1px solid rgba(16, 185, 129, 0.2);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        }
        .login-title {
            color: #f9fafb;
            font-size: 2rem;
            font-weight: 700;
            text-align: center;
            margin-bottom: 0.5rem;
        }
        .login-subtitle {
            color: #94a3b8;
            text-align: center;
            margin-bottom: 2rem;
        }
        </style>
    """, unsafe_allow_html=True)
    
    st.markdown("""
        <div class="login-container">
            <div class="login-title">🏌️ TeeMail Dashboard</div>
            <div class="login-subtitle">Booking Management System</div>
        </div>
    """, unsafe_allow_html=True)
    
    with st.form("login_form"):
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        submit = st.form_submit_button("🔐 Login", use_container_width=True)
        
        if submit:
            if username and password:
                success, customer_id, full_name, must_change, user_id = authenticate_user(username, password)
                
                if success:
                    st.session_state.authenticated = True
                    st.session_state.customer_id = customer_id
                    st.session_state.username = username
                    st.session_state.full_name = full_name
                    st.session_state.user_id = user_id
                    
                    if must_change:
                        st.session_state.must_change_password = True
                        st.session_state.show_password_change = True
                        st.success("✅ Please set your password...")
                        st.rerun()
                    else:
                        update_last_login(user_id)
                        st.success("✅ Login successful!")
                        st.rerun()
                else:
                    st.error("❌ Invalid username or password")
            else:
                st.error("❌ Please enter username and password")
    
    st.markdown("""
        <div style='text-align: center; color: #6b7280; font-size: 0.85rem; margin-top: 2rem;'>
            <p>First time? Use your temporary password</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.stop()


# ========================================
# LOAD BOOKINGS
# ========================================
@st.cache_data(ttl=10)
def load_bookings_from_db(club_filter):
    """Load bookings directly from PostgreSQL database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        cursor.execute("""
            SELECT
                id, booking_id, guest_email, date, tee_time, players, total,
                status, note, club, timestamp, customer_confirmed_at,
                updated_at, updated_by, created_at
            FROM bookings
            WHERE club = %s
            ORDER BY timestamp DESC
        """, (club_filter,))

        bookings = cursor.fetchall()
        cursor.close()
        conn.close()

        if not bookings:
            return pd.DataFrame(), 'postgresql'

        df = pd.DataFrame(bookings)

        # Ensure all datetime columns are properly converted
        for col in ['timestamp', 'customer_confirmed_at', 'updated_at', 'created_at']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')

        # Ensure tee_time exists and handle None/NaN values
        if 'tee_time' not in df.columns:
            df['tee_time'] = 'Not Specified'
        else:
            df['tee_time'] = df['tee_time'].fillna('Not Specified')

        # Extract tee times from note content if not already set
        for idx in df.index:
            current_tee_time = df.at[idx, 'tee_time']
            if current_tee_time in ['Not Specified', None, ''] or pd.isna(current_tee_time):
                note_content = df.at[idx, 'note']
                extracted_time = extract_tee_time_from_note(note_content)
                if extracted_time:
                    df.at[idx, 'tee_time'] = extracted_time

        # Ensure note column exists and handle None/NaN
        if 'note' not in df.columns:
            df['note'] = 'No additional information provided'
        else:
            df['note'] = df['note'].fillna('No additional information provided')

        # Ensure all required columns have proper defaults
        if 'status' not in df.columns:
            df['status'] = 'Inquiry'

        if 'players' not in df.columns:
            df['players'] = 1
        else:
            df['players'] = df['players'].fillna(1)

        if 'total' not in df.columns:
            df['total'] = 0.0
        else:
            df['total'] = df['total'].fillna(0.0)

        if 'guest_email' not in df.columns:
            df['guest_email'] = 'No email provided'
        else:
            df['guest_email'] = df['guest_email'].fillna('No email provided')

        if 'booking_id' not in df.columns:
            df['booking_id'] = df.index.map(lambda x: f'BOOK-{x:04d}')

        return df, 'postgresql'
    except Exception as e:
        st.error(f"❌ Database error: {e}")
        import traceback
        st.error(f"Details: {traceback.format_exc()}")
        return pd.DataFrame(), 'error'


def update_booking_status(booking_id: str, new_status: str, updated_by: str):
    """Update booking status in database and return True to trigger filter adjustment"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE bookings
            SET status = %s, updated_at = NOW(), updated_by = %s
            WHERE booking_id = %s;
        """, (new_status, updated_by, booking_id))

        conn.commit()
        cursor.close()
        conn.close()

        # Store the new status in session state to auto-include in filter
        if 'auto_include_status' not in st.session_state:
            st.session_state.auto_include_status = set()
        st.session_state.auto_include_status.add(new_status)

        return True
    except Exception as e:
        st.error(f"Error updating status: {e}")
        return False


def update_booking_tee_time(booking_id: str, tee_time: str):
    """Update booking tee_time in database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE bookings
            SET tee_time = %s, updated_at = NOW()
            WHERE booking_id = %s;
        """, (tee_time, booking_id))

        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error updating tee time: {e}")
        return False


def fix_all_tee_times(club_filter):
    """Extract and update tee times for all bookings with missing tee times"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        # Get all bookings with missing or "Not Specified" tee times
        cursor.execute("""
            SELECT id, booking_id, note, tee_time
            FROM bookings
            WHERE club = %s
              AND (tee_time IS NULL OR tee_time = 'Not Specified' OR tee_time = '');
        """, (club_filter,))

        bookings = cursor.fetchall()

        if not bookings:
            cursor.close()
            conn.close()
            return 0, 0

        updated_count = 0
        not_found_count = 0

        for booking in bookings:
            note = booking['note']
            extracted_time = extract_tee_time_from_note(note)

            if extracted_time:
                # Update the booking
                cursor.execute("""
                    UPDATE bookings
                    SET tee_time = %s, updated_at = NOW()
                    WHERE id = %s;
                """, (extracted_time, booking['id']))
                updated_count += 1
            else:
                not_found_count += 1

        # Commit all updates
        conn.commit()
        cursor.close()
        conn.close()

        return updated_count, not_found_count

    except Exception as e:
        st.error(f"Error fixing tee times: {e}")
        return 0, 0


def delete_booking(booking_id: str):
    """Delete a booking from the database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM bookings
            WHERE booking_id = %s;
        """, (booking_id,))

        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error deleting booking: {e}")
        return False


def update_booking_note(booking_id: str, note: str):
    """Update booking note in database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE bookings
            SET note = %s, updated_at = NOW()
            WHERE booking_id = %s;
        """, (note, booking_id))

        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error updating note: {e}")
        return False


# ========================================
# MAIN DASHBOARD
# ========================================

with st.sidebar:
    st.markdown(f"""
        <div style='text-align: center; padding: 1.5rem 1rem; border-bottom: 1px solid #1e293b; margin-bottom: 1.5rem;'>
            <h2 style='color: #10b981; margin: 0; font-size: 1.5rem; font-weight: 700; letter-spacing: -0.5px;'>TeeMail</h2>
            <p style='color: #64748b; font-size: 0.8125rem; margin-top: 0.375rem; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;'>Booking Dashboard</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown(f"<div class='user-badge'>{st.session_state.full_name}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='club-badge'>{st.session_state.customer_id.title()}</div>", unsafe_allow_html=True)

    st.markdown("<div style='height: 1px; background: #1e293b; margin: 1.5rem 0;'></div>", unsafe_allow_html=True)

    if st.button("Logout", use_container_width=True):
        logout()
        st.rerun()
    
    st.markdown("<div style='height: 1px; background: #1e293b; margin: 1.5rem 0;'></div>", unsafe_allow_html=True)

    st.markdown("#### Filters")

    # Initialize filter state
    if 'auto_include_status' not in st.session_state:
        st.session_state.auto_include_status = set()
    if 'clicked_status_filter' not in st.session_state:
        st.session_state.clicked_status_filter = None
    if 'date_filter_preset' not in st.session_state:
        st.session_state.date_filter_preset = "Next 30 Days"

    # Date preset selector
    date_preset = st.selectbox(
        "Date Preset",
        ["Today", "Next 7 Days", "Next 30 Days", "Next 60 Days", "Next 90 Days", "All Upcoming", "Custom"],
        index=2  # Default to "Next 30 Days"
    )

    # Calculate date range based on preset
    if date_preset == "Today":
        date_range = (datetime.now().date(), datetime.now().date())
    elif date_preset == "Next 7 Days":
        date_range = (datetime.now().date(), datetime.now().date() + timedelta(days=7))
    elif date_preset == "Next 30 Days":
        date_range = (datetime.now().date(), datetime.now().date() + timedelta(days=30))
    elif date_preset == "Next 60 Days":
        date_range = (datetime.now().date(), datetime.now().date() + timedelta(days=60))
    elif date_preset == "Next 90 Days":
        date_range = (datetime.now().date(), datetime.now().date() + timedelta(days=90))
    elif date_preset == "All Upcoming":
        date_range = (datetime.now().date(), datetime.now().date() + timedelta(days=365))
    else:  # Custom
        date_range = st.date_input(
            "Custom Date Range",
            value=(datetime.now().date(), datetime.now().date() + timedelta(days=30))
        )

    # Status filter - if clicked from metric card, use that
    if st.session_state.clicked_status_filter:
        default_statuses = [st.session_state.clicked_status_filter]
    else:
        # Merge default statuses with auto-included ones
        default_statuses = ["Inquiry", "Requested", "Confirmed", "Booked", "Pending"]
        default_statuses = list(set(default_statuses) | st.session_state.auto_include_status)

    status_filter = st.multiselect(
        "Status",
        ["Inquiry", "Requested", "Confirmed", "Booked", "Rejected", "Cancelled", "Pending"],
        default=default_statuses
    )

    # Clear filter button
    if st.button("Clear All Filters", use_container_width=True):
        st.session_state.clicked_status_filter = None
        st.cache_data.clear()
        st.rerun()

st.markdown("""
    <h1 style='margin-bottom: 0.5rem;'>Booking Requests</h1>
    <p style='color: #64748b; margin-bottom: 1rem; font-size: 0.9375rem;'>Manage and track all incoming tee time requests</p>
""", unsafe_allow_html=True)

# Show active filter indicator
if st.session_state.clicked_status_filter:
    st.markdown(f"""
        <div style='background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 1.5rem; display: flex; align-items: center; justify-content: space-between;'>
            <div style='display: flex; align-items: center; gap: 0.5rem;'>
                <span style='font-size: 1.25rem;'>🎯</span>
                <span style='color: #10b981; font-weight: 600;'>Filtering by: {st.session_state.clicked_status_filter}</span>
            </div>
        </div>
    """, unsafe_allow_html=True)
else:
    st.markdown("<div style='margin-bottom: 1rem;'></div>", unsafe_allow_html=True)

df, source = load_bookings_from_db(st.session_state.customer_id)

if df.empty:
    st.info("No bookings found")
    st.stop()

filtered_df = df.copy()
if status_filter:
    filtered_df = filtered_df[filtered_df['status'].isin(status_filter)]

# Handle date range filtering
if date_range:
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
        filtered_df = filtered_df[
            (filtered_df['date'].dt.date >= start_date) &
            (filtered_df['date'].dt.date <= end_date)
        ]
    elif hasattr(date_range, '__len__') and len(date_range) == 2:
        start_date, end_date = date_range[0], date_range[1]
        filtered_df = filtered_df[
            (filtered_df['date'].dt.date >= start_date) &
            (filtered_df['date'].dt.date <= end_date)
        ]

col1, col2, col3, col4 = st.columns(4)

# Calculate counts for all statuses (before filtering)
all_inquiry_count = len(df[df['status'].isin(['Inquiry', 'Pending'])])
all_requested_count = len(df[df['status'] == 'Requested'])
all_confirmed_count = len(df[df['status'] == 'Confirmed'])
all_booked_count = len(df[df['status'] == 'Booked'])

with col1:
    inquiry_count = len(filtered_df[filtered_df['status'].isin(['Inquiry', 'Pending'])])
    if st.button(f"🔵 Inquiry\n{all_inquiry_count}", key="filter_inquiry", use_container_width=True, help="Click to filter Inquiry status"):
        st.session_state.clicked_status_filter = "Inquiry"
        st.cache_data.clear()
        st.rerun()
    st.markdown(f"<div style='text-align: center; color: #64748b; font-size: 0.75rem; margin-top: -0.5rem;'>Showing: {inquiry_count}</div>", unsafe_allow_html=True)

with col2:
    requested_count = len(filtered_df[filtered_df['status'] == 'Requested'])
    if st.button(f"🟡 Requested\n{all_requested_count}", key="filter_requested", use_container_width=True, help="Click to filter Requested status"):
        st.session_state.clicked_status_filter = "Requested"
        st.cache_data.clear()
        st.rerun()
    st.markdown(f"<div style='text-align: center; color: #64748b; font-size: 0.75rem; margin-top: -0.5rem;'>Showing: {requested_count}</div>", unsafe_allow_html=True)

with col3:
    confirmed_count = len(filtered_df[filtered_df['status'] == 'Confirmed'])
    if st.button(f"🟠 Confirmed\n{all_confirmed_count}", key="filter_confirmed", use_container_width=True, help="Click to filter Confirmed status"):
        st.session_state.clicked_status_filter = "Confirmed"
        st.cache_data.clear()
        st.rerun()
    st.markdown(f"<div style='text-align: center; color: #64748b; font-size: 0.75rem; margin-top: -0.5rem;'>Showing: {confirmed_count}</div>", unsafe_allow_html=True)

with col4:
    booked_count = len(filtered_df[filtered_df['status'] == 'Booked'])
    if st.button(f"✅ Booked\n{all_booked_count}", key="filter_booked", use_container_width=True, help="Click to filter Booked status"):
        st.session_state.clicked_status_filter = "Booked"
        st.cache_data.clear()
        st.rerun()
    st.markdown(f"<div style='text-align: center; color: #64748b; font-size: 0.75rem; margin-top: -0.5rem;'>Showing: {booked_count}</div>", unsafe_allow_html=True)

st.markdown("<div style='height: 1px; background: #1e293b; margin: 2rem 0;'></div>", unsafe_allow_html=True)

# Format date range string
if date_range:
    if isinstance(date_range, tuple) and len(date_range) == 2:
        date_str = f"{date_range[0].strftime('%b %d')} to {date_range[1].strftime('%b %d, %Y')}"
    elif hasattr(date_range, '__len__') and len(date_range) == 2:
        date_str = f"{date_range[0].strftime('%b %d')} to {date_range[1].strftime('%b %d, %Y')}"
    else:
        date_str = "all dates"
else:
    date_str = "all dates"

st.markdown(f"""
    <div style='margin-bottom: 1.5rem;'>
        <h3 style='color: #f9fafb; font-weight: 600; font-size: 1.125rem;'>{len(filtered_df)} Active Requests</h3>
        <p style='color: #64748b; font-size: 0.875rem; margin-top: 0.25rem;'>Showing bookings from {date_str}</p>
    </div>
""", unsafe_allow_html=True)

# ========================================
# BOOKING CARDS - ENHANCED VERSION
# ========================================
for idx, booking in filtered_df.iterrows():
    status_icon = get_status_icon(booking['status'])
    status_class = get_status_color(booking['status'])

    tee_time_display = booking.get('tee_time', 'Not Specified')
    if tee_time_display == 'None' or tee_time_display is None or pd.isna(tee_time_display):
        tee_time_display = 'Not Specified'

    note_content = booking.get('note', '')
    if note_content is None or pd.isna(note_content):
        note_content = 'No additional information provided'

    # Prepare progress bar data
    current_status = booking['status']
    if current_status == 'Pending':
        current_status = 'Inquiry'

    stages = [
        {'name': 'Inquiry', 'color': '#60a5fa'},
        {'name': 'Requested', 'color': '#eab308'},
        {'name': 'Confirmed', 'color': '#f97316'},
        {'name': 'Booked', 'color': '#10b981'}
    ]

    is_rejected = current_status == 'Rejected'
    is_cancelled = current_status == 'Cancelled'
    current_index = next((i for i, s in enumerate(stages) if s['name'] == current_status), 0)
    progress_width = (current_index / (len(stages) - 1)) * 100 if len(stages) > 1 else 0

    # Format requested time
    requested_time = booking['timestamp'].strftime('%b %d • %I:%M %p')

    with st.container():
        # Build progress bar HTML inline
        if is_rejected or is_cancelled:
            status_color = '#ef4444' if is_rejected else '#64748b'
            progress_html = f"<div style='background: #0a0f1e; padding: 1rem; border-radius: 8px; border: 1px solid #1e293b;'><div style='display: flex; align-items: center; justify-content: center; gap: 0.75rem;'><div style='width: 12px; height: 12px; border-radius: 50%; background: {status_color};'></div><span style='color: {status_color}; font-weight: 700; font-size: 1rem; text-transform: uppercase; letter-spacing: 0.5px;'>{current_status}</span></div></div>"
        else:
            # Build stage nodes HTML
            stages_html = ""
            for i, stage in enumerate(stages):
                is_active = i <= current_index
                is_current = i == current_index
                bg_color = stage['color'] if is_active else '#1e293b'
                text_color = '#f9fafb' if is_active else '#64748b'
                border_color = stage['color'] if is_current else ('#2d3748' if is_active else '#1e293b')
                box_shadow = '0 0 0 4px rgba(16, 185, 129, 0.2)' if is_current else 'none'
                font_weight = '700' if is_current else '600'

                stages_html += f"<div style='display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative;'><div style='width: 1.5rem; height: 1.5rem; border-radius: 50%; background: {bg_color}; border: 3px solid {border_color}; box-shadow: {box_shadow}; transition: all 0.3s ease;'></div><div style='margin-top: 0.5rem; font-size: 0.7rem; font-weight: {font_weight}; color: {text_color}; text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap;'>{stage['name']}</div></div>"

            progress_html = f"<div style='background: #0a0f1e; padding: 1.25rem; border-radius: 8px; border: 1px solid #1e293b;'><div style='display: flex; align-items: center; justify-content: space-between; position: relative;'><div style='position: absolute; top: 0.75rem; left: 2rem; right: 2rem; height: 3px; background: #1e293b; z-index: 1;'></div><div style='position: absolute; top: 0.75rem; left: 2rem; width: calc({progress_width}% - 2rem); height: 3px; background: linear-gradient(90deg, #60a5fa, #10b981); z-index: 2;'></div>{stages_html}</div></div>"

        # Build complete card HTML including progress bar and details
        card_html = f"""<div class='booking-card' style='background: linear-gradient(135deg, #141b2b 0%, #1a2332 100%); border: 1px solid #1e293b; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3); transition: all 0.3s ease;'><div style='display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1.25rem;'><div style='flex: 1;'><div class='booking-id' style='margin-bottom: 0.5rem;'>{html.escape(str(booking['booking_id']))}</div><div class='booking-email'>{html.escape(str(booking['guest_email']))}</div></div><div style='text-align: right;'><div class='timestamp'>REQUESTED</div><div class='timestamp-value'>{requested_time}</div></div></div><div style='margin-bottom: 1.5rem;'>{progress_html}</div><div style='height: 1px; background: linear-gradient(90deg, transparent, #1e293b, transparent); margin: 1.5rem 0;'></div><div style='display: grid; grid-template-columns: repeat(4, 1fr); gap: 1.5rem; margin-bottom: 1.5rem;'><div><div class='data-label' style='margin-bottom: 0.5rem;'>TEE DATE</div><div style='font-size: 1rem; font-weight: 600; color: #f9fafb;'>{booking['date'].strftime('%b %d, %Y')}</div></div><div><div class='data-label' style='margin-bottom: 0.5rem;'>TEE TIME</div><div style='font-size: 1rem; font-weight: 600; color: #f9fafb;'>{tee_time_display}</div></div><div><div class='data-label' style='margin-bottom: 0.5rem;'>PLAYERS</div><div style='font-size: 1rem; font-weight: 600; color: #f9fafb;'>{booking['players']}</div></div><div><div class='data-label' style='margin-bottom: 0.5rem;'>TOTAL</div><div style='font-size: 1.5rem; font-weight: 700; color: #10b981;'>${booking['total']:,.2f}</div></div></div></div>"""

        # Render the complete card
        st.markdown(card_html, unsafe_allow_html=True)

        # Quick status change buttons (above the expander)
        if not is_rejected and not is_cancelled:
            st.markdown("<div style='margin: -0.5rem 0 1rem 0;'>", unsafe_allow_html=True)
            status_col1, status_col2, status_col3, status_col4, status_col5 = st.columns([1, 1, 1, 1, 2])

            with status_col1:
                if booking['status'] in ['Inquiry', 'Pending']:
                    if st.button("→ Requested", key=f"quick_req_{booking['booking_id']}", use_container_width=True, help="Move to Requested"):
                        if update_booking_status(booking['booking_id'], 'Requested', st.session_state.username):
                            st.cache_data.clear()
                            st.rerun()

            with status_col2:
                if booking['status'] == 'Requested':
                    if st.button("→ Confirmed", key=f"quick_conf_{booking['booking_id']}", use_container_width=True, help="Move to Confirmed"):
                        if update_booking_status(booking['booking_id'], 'Confirmed', st.session_state.username):
                            st.cache_data.clear()
                            st.rerun()

            with status_col3:
                if booking['status'] == 'Confirmed':
                    if st.button("→ Booked", key=f"quick_book_{booking['booking_id']}", use_container_width=True, help="Move to Booked"):
                        if update_booking_status(booking['booking_id'], 'Booked', st.session_state.username):
                            st.cache_data.clear()
                            st.rerun()

            with status_col4:
                if booking['status'] not in ['Rejected', 'Cancelled', 'Booked']:
                    if st.button("✕ Reject", key=f"quick_rej_{booking['booking_id']}", use_container_width=True, help="Reject this booking"):
                        if update_booking_status(booking['booking_id'], 'Rejected', st.session_state.username):
                            st.cache_data.clear()
                            st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)

        with st.expander("View Full Details", expanded=False):
            detail_col1, detail_col2 = st.columns([2, 1])

            with detail_col1:
                st.markdown("""
                    <div style='background: #0f1419; padding: 0.75rem 1rem; border-radius: 8px 8px 0 0; border: 1px solid #1e293b; border-bottom: none; margin-bottom: 0;'>
                        <div class='data-label' style='margin: 0;'>BOOKING NOTES</div>
                    </div>
                """, unsafe_allow_html=True)

                # Editable notes text area
                updated_note = st.text_area(
                    label="Notes",
                    value=note_content,
                    height=200,
                    disabled=False,
                    label_visibility="collapsed",
                    key=f"note_{booking['booking_id']}"
                )

                # Save notes button
                if updated_note != note_content:
                    if st.button("💾 Save Notes", key=f"save_note_{booking['booking_id']}", use_container_width=True):
                        if update_booking_note(booking['booking_id'], updated_note):
                            st.success("Notes saved successfully!")
                            st.cache_data.clear()
                            st.rerun()
                
                if booking.get('updated_by') and not pd.isna(booking.get('updated_by')):
                    st.markdown(f"""
                        <div style='margin-top: 1.5rem; padding: 1rem; background: #0f1419; border-radius: 8px; border: 1px solid #1e293b;'>
                            <div class='data-label'>LAST UPDATED</div>
                            <div style='color: #cbd5e1; font-size: 0.875rem; margin-top: 0.5rem;'>{booking['updated_at'].strftime('%b %d, %Y • %I:%M %p')}</div>
                            <div style='color: #64748b; font-size: 0.8125rem; margin-top: 0.25rem;'>by {booking['updated_by']}</div>
                        </div>
                    """, unsafe_allow_html=True)
            
            with detail_col2:
                st.markdown("### Quick Actions")

                current_status = booking['status']

                if current_status in ['Inquiry', 'Pending']:
                    if st.button("Mark as Requested", key=f"req_{booking['booking_id']}", use_container_width=True):
                        if update_booking_status(booking['booking_id'], 'Requested', st.session_state.username):
                            st.success("Updated")
                            st.cache_data.clear()
                            st.rerun()

                if current_status == 'Requested':
                    if st.button("Mark as Confirmed", key=f"conf_{booking['booking_id']}", use_container_width=True):
                        if update_booking_status(booking['booking_id'], 'Confirmed', st.session_state.username):
                            st.success("Updated")
                            st.cache_data.clear()
                            st.rerun()

                if current_status == 'Confirmed':
                    if st.button("Mark as Booked", key=f"book_{booking['booking_id']}", use_container_width=True):
                        if update_booking_status(booking['booking_id'], 'Booked', st.session_state.username):
                            st.success("Updated")
                            st.cache_data.clear()
                            st.rerun()

                if current_status not in ['Rejected', 'Cancelled', 'Booked']:
                    st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)
                    if st.button("Reject", key=f"rej_{booking['booking_id']}", use_container_width=True):
                        if update_booking_status(booking['booking_id'], 'Rejected', st.session_state.username):
                            st.warning("Rejected")
                            st.cache_data.clear()
                            st.rerun()

                # Delete booking button (with confirmation)
                st.markdown("<div style='margin-top: 1.5rem; border-top: 1px solid #1e293b; padding-top: 1rem;'></div>", unsafe_allow_html=True)
                st.markdown("<div style='color: #dc2626; font-weight: 600; font-size: 0.875rem; margin-bottom: 0.5rem;'>Danger Zone</div>", unsafe_allow_html=True)

                # Initialize session state for delete confirmation
                if f"confirm_delete_{booking['booking_id']}" not in st.session_state:
                    st.session_state[f"confirm_delete_{booking['booking_id']}"] = False

                if not st.session_state[f"confirm_delete_{booking['booking_id']}"]:
                    if st.button("🗑️ Delete Booking", key=f"del_{booking['booking_id']}", use_container_width=True, type="secondary"):
                        st.session_state[f"confirm_delete_{booking['booking_id']}"] = True
                        st.rerun()
                else:
                    st.warning("⚠️ Are you sure? This action cannot be undone.")
                    col_confirm1, col_confirm2 = st.columns(2)
                    with col_confirm1:
                        if st.button("✓ Yes, Delete", key=f"confirm_del_{booking['booking_id']}", use_container_width=True):
                            if delete_booking(booking['booking_id']):
                                st.success("Booking deleted successfully!")
                                st.cache_data.clear()
                                st.session_state[f"confirm_delete_{booking['booking_id']}"] = False
                                st.rerun()
                    with col_confirm2:
                        if st.button("✕ Cancel", key=f"cancel_del_{booking['booking_id']}", use_container_width=True):
                            st.session_state[f"confirm_delete_{booking['booking_id']}"] = False
                            st.rerun()

st.markdown("<div style='height: 1px; background: #1e293b; margin: 2rem 0;'></div>", unsafe_allow_html=True)
st.markdown("#### Export Options")
col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("Export to Excel", use_container_width=True):
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            filtered_df.to_excel(writer, index=False, sheet_name='Bookings')

        st.download_button(
            label="Download Excel",
            data=output.getvalue(),
            file_name=f"bookings_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

with col2:
    if st.button("Export to CSV", use_container_width=True):
        csv = filtered_df.to_csv(index=False)
        st.download_button(
            label="Download CSV",
            data=csv,
            file_name=f"bookings_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True
        )

with col3:
    if st.button("Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with col4:
    if st.button("Fix Tee Times", use_container_width=True):
        with st.spinner("Extracting tee times from email content..."):
            updated, not_found = fix_all_tee_times(st.session_state.customer_id)
            if updated > 0:
                st.success(f"✅ Updated {updated} booking(s) with extracted tee times!")
                st.cache_data.clear()
                st.rerun()
            elif not_found > 0:
                st.warning(f"⚠️ Could not extract tee times from {not_found} booking(s)")
            else:
                st.info("All bookings already have tee times set")
