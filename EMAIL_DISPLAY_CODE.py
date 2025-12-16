"""
Code to display inbound emails in booking details
Copy these sections into your dashboard
"""

import html
from datetime import datetime

# ============================================================================
# STEP 1: DATABASE FUNCTION (add to your database functions section)
# ============================================================================

def load_emails_by_booking_id(booking_id, guest_email=None):
    """Load inbound emails for a specific booking

    Matches emails by:
    1. booking_id field (if populated)
    2. from_email matching guest_email (for emails not yet linked)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        # Query emails that either have the booking_id OR match the guest email
        if guest_email:
            cursor.execute("""
                SELECT * FROM inbound_emails
                WHERE booking_id = %s
                   OR (booking_id IS NULL AND from_email ILIKE %s)
                   OR (booking_id IS NULL AND to_email ILIKE %s)
                ORDER BY received_at DESC
            """, (booking_id, f"%{guest_email}%", f"%{guest_email}%"))
        else:
            cursor.execute("""
                SELECT * FROM inbound_emails
                WHERE booking_id = %s
                ORDER BY received_at DESC
            """, (booking_id,))

        emails = cursor.fetchall()
        cursor.close()
        conn.close()

        if not emails:
            return []

        # Convert to list of dicts and format dates
        result = []
        for email in emails:
            email_dict = dict(email)
            # Convert timestamp columns to formatted strings
            if 'received_at' in email_dict and email_dict['received_at']:
                email_dict['received_at_formatted'] = email_dict['received_at'].strftime('%b %d, %Y %I:%M %p')
            else:
                email_dict['received_at_formatted'] = 'N/A'
            result.append(email_dict)

        return result
    except Exception as e:
        st.error(f"Error loading emails: {e}")
        return []


# ============================================================================
# STEP 2: EMAIL DISPLAY CODE (add inside your booking details expander)
# ============================================================================

# Place this code inside: with st.expander("View Full Details", expanded=False):
# After your notes section, add:

# Display inbound emails for this booking
st.markdown("""
    <div style='background: #4a6278; padding: 0.75rem 1rem; border-radius: 8px 8px 0 0; border: 2px solid #6b7c3f; border-bottom: none; margin-top: 1.5rem; margin-bottom: 0;'>
        <div style='color: #d4b896; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin: 0;'>Inbound Emails</div>
    </div>
""", unsafe_allow_html=True)

emails = load_emails_by_booking_id(booking['booking_id'], booking.get('guest_email'))

if not emails:
    st.markdown("""
        <div style='background: #3d5266; padding: 1rem; border: 2px solid #6b7c3f; border-top: none; border-radius: 0 0 8px 8px;'>
            <div style='color: #94a3b8; font-size: 0.875rem; text-align: center;'>No emails found for this booking</div>
        </div>
    """, unsafe_allow_html=True)
else:
    st.markdown(f"""
        <div style='background: #3d5266; padding: 1rem; border: 2px solid #6b7c3f; border-top: none; border-radius: 0 0 8px 8px;'>
            <div style='color: #10b981; font-size: 0.875rem; font-weight: 600; margin-bottom: 0.75rem;'>{len(emails)} email(s) found</div>
    """, unsafe_allow_html=True)

    for email_idx, email in enumerate(emails):
        # Determine status color and text
        if email.get('processed'):
            status_color = '#10b981'
            status_text = 'Processed'
        elif email.get('error_message'):
            status_color = '#ef4444'
            status_text = 'Error'
        else:
            status_color = '#fbbf24'
            status_text = 'Unprocessed'

        # Email type color
        email_type = email.get('email_type', 'unknown')
        email_type_color = {
            'inquiry': '#3b82f6',
            'booking_request': '#8b5cf6',
            'staff_confirmation': '#10b981',
            'waitlist_optin': '#f59e0b',
            'customer_reply': '#6366f1'
        }.get(email_type, '#64748b')

        subject = html.escape(str(email.get('subject') or 'No Subject'))
        from_email = html.escape(str(email.get('from_email') or 'N/A'))
        received_at = email.get('received_at_formatted', 'N/A')

        st.markdown(f"""
            <div style='background: #2d3e50; padding: 0.75rem; border-radius: 6px; margin-bottom: 0.5rem; border-left: 3px solid {status_color};'>
                <div style='display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.5rem;'>
                    <div style='flex: 1;'>
                        <div style='color: #f9fafb; font-weight: 600; font-size: 0.875rem;'>{subject}</div>
                        <div style='color: #3b82f6; font-size: 0.75rem; margin-top: 0.25rem;'>From: {from_email}</div>
                    </div>
                </div>
                <div style='display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;'>
                    <div style='background: {email_type_color}20; border: 1px solid {email_type_color}; color: {email_type_color}; padding: 0.25rem 0.5rem; border-radius: 4px; font-weight: 600; font-size: 0.65rem; text-transform: uppercase;'>
                        {email_type}
                    </div>
                    <div style='background: {status_color}20; border: 1px solid {status_color}; color: {status_color}; padding: 0.25rem 0.5rem; border-radius: 4px; font-weight: 600; font-size: 0.65rem; text-transform: uppercase;'>
                        {status_text}
                    </div>
                    <div style='color: #64748b; font-size: 0.7rem; margin-left: auto;'>{received_at}</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        # Show email body details (no expander since we're already inside one)
        body_text = email.get('body_text') or 'No body text available'

        # Show metadata
        col_email1, col_email2 = st.columns(2)
        with col_email1:
            message_id = email.get('message_id') or 'N/A'
            display_id = message_id[:30] if len(message_id) > 30 else message_id
            st.caption(f"📧 Message ID: {display_id}...")
        with col_email2:
            processing_status = email.get('processing_status')
            if processing_status:
                st.caption(f"📊 Status: {processing_status}")

        # Show email body in collapsed text area
        st.text_area(
            "Email Body",
            value=body_text,
            height=100,
            disabled=True,
            key=f"email_body_{booking['booking_id']}_{email_idx}",
            label_visibility="collapsed"
        )

        if email.get('error_message'):
            st.error(f"⚠️ Error: {email.get('error_message')}")

        # Add spacing between emails
        st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================================
# STEP 3: REQUIRED IMPORTS (add at top of file)
# ============================================================================

"""
import streamlit as st
import pandas as pd
import html
from datetime import datetime
import psycopg
from psycopg.rows import dict_row
"""


# ============================================================================
# INTEGRATION NOTES
# ============================================================================

"""
1. Add the load_emails_by_booking_id() function to your database functions section

2. Inside your booking details expander, after the notes section, add the email display code

3. The structure should be:

   with st.expander("View Full Details", expanded=False):
       # ... your notes section ...

       # ADD EMAIL DISPLAY CODE HERE
       st.markdown(...)  # Email header
       emails = load_emails_by_booking_id(...)
       # ... rest of email display code ...

4. Make sure you have:
   - psycopg connection with dict_row factory
   - inbound_emails table with columns: id, message_id, from_email, to_email,
     subject, body_text, received_at, processed, email_type, booking_id,
     error_message, processing_status

5. Adjust colors to match your theme if needed
"""
