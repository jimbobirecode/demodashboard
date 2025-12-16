# Dashboard Styling Guide

This guide contains reusable styling patterns from the TeeMail dashboard.

## Color Palette

```python
COLORS = {
    # Primary Colors
    'emerald_dark': '#059669',
    'emerald': '#10b981',
    'blue_dark': '#1e3a8a',
    'blue_medium': '#1e40af',
    'blue': '#3b82f6',
    'amber': '#fbbf24',

    # Status Colors
    'success': '#10b981',
    'warning': '#fbbf24',
    'error': '#ef4444',
    'info': '#3b82f6',
    'purple': '#a78bfa',
    'indigo': '#6366f1',

    # Text Colors
    'text_primary': '#f9fafb',
    'text_secondary': '#ffffff',
    'text_muted': '#64748b',
    'text_light': '#94a3b8',

    # Background Colors
    'bg_card': '#1e3a8a to #1e40af',
    'bg_section': '#4a6278',
    'bg_content': '#3d5266',
    'bg_dark': '#2d3e50',

    # Border Colors
    'border_primary': '#10b981',
    'border_secondary': '#6b7c3f',
    'border_accent': '#3b82f6',
}
```

## Component Patterns

### 1. Page Header

```python
st.markdown("""
    <h2 style='margin-bottom: 0.5rem;'>Page Title</h2>
    <p style='color: #ffffff; margin-bottom: 1.5rem; font-size: 0.9375rem;'>
        Subtitle or description text
    </p>
""", unsafe_allow_html=True)
```

### 2. Metric Cards (Statistics)

```python
# Create 4 columns for metrics
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
        <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%);
                    border: 2px solid #10b981;
                    border-radius: 12px;
                    padding: 1.5rem;
                    text-align: center;'>
            <div style='color: #ffffff;
                        font-size: 0.75rem;
                        font-weight: 700;
                        text-transform: uppercase;'>
                Metric Label
            </div>
            <div style='color: #fbbf24;
                        font-size: 2.5rem;
                        font-weight: 700;'>
                {count}
            </div>
        </div>
    """, unsafe_allow_html=True)
```

### 3. Main Content Card

```python
card_html = f"""
<div style='background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
            border: 2px solid #10b981;
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1rem;
            box-shadow: 0 4px 16px rgba(59, 130, 246, 0.3);'>

    <!-- Header Section -->
    <div style='display: flex;
                justify-content: space-between;
                align-items: flex-start;
                margin-bottom: 1.25rem;'>
        <div style='flex: 1;'>
            <div style='color: #f9fafb;
                        font-weight: 700;
                        font-size: 1rem;'>
                Title
            </div>
            <div style='color: #3b82f6;
                        font-size: 0.875rem;'>
                Subtitle
            </div>
        </div>
        <div style='text-align: right;'>
            <div style='color: #64748b;
                        font-size: 0.7rem;
                        text-transform: uppercase;'>
                Label
            </div>
            <div style='color: #f9fafb;
                        font-weight: 600;'>
                Value
            </div>
        </div>
    </div>

    <!-- Divider -->
    <div style='height: 1px;
                background: linear-gradient(90deg, transparent, #3b82f6, transparent);
                margin: 1.5rem 0;'></div>

    <!-- Content Grid -->
    <div style='display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 1.5rem;
                margin-bottom: 1rem;'>
        <div>
            <div style='color: #64748b;
                        font-size: 0.7rem;
                        text-transform: uppercase;
                        margin-bottom: 0.5rem;'>
                Field Label
            </div>
            <div style='font-size: 1rem;
                        font-weight: 600;
                        color: #f9fafb;'>
                Field Value
            </div>
        </div>
    </div>
</div>
"""
st.markdown(card_html, unsafe_allow_html=True)
```

### 4. Status Badges

```python
# Define status colors
status_colors = {
    'success': '#10b981',
    'warning': '#fbbf24',
    'error': '#ef4444',
    'info': '#3b82f6',
    'pending': '#8b5cf6',
}

status_color = status_colors.get(status, '#64748b')

badge_html = f"""
<div style='background: {status_color}20;
            border: 2px solid {status_color};
            color: {status_color};
            padding: 0.375rem 0.75rem;
            border-radius: 6px;
            font-weight: 600;
            font-size: 0.75rem;
            text-transform: uppercase;
            display: inline-block;'>
    {status_text}
</div>
"""
```

### 5. Section Header with Background

```python
st.markdown("""
    <div style='background: #4a6278;
                padding: 0.75rem 1rem;
                border-radius: 8px 8px 0 0;
                border: 2px solid #6b7c3f;
                border-bottom: none;
                margin-top: 1.5rem;
                margin-bottom: 0;'>
        <div style='color: #d4b896;
                    font-size: 0.75rem;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    margin: 0;'>
            Section Title
        </div>
    </div>
""", unsafe_allow_html=True)
```

### 6. Content Box (matches section header)

```python
st.markdown("""
    <div style='background: #3d5266;
                padding: 1rem;
                border: 2px solid #6b7c3f;
                border-top: none;
                border-radius: 0 0 8px 8px;'>
        <div style='color: #94a3b8;
                    font-size: 0.875rem;
                    text-align: center;'>
            Content here
        </div>
    </div>
""", unsafe_allow_html=True)
```

### 7. Compact Card (for list items)

```python
# With left border for status indication
st.markdown(f"""
    <div style='background: #2d3e50;
                padding: 0.75rem;
                border-radius: 6px;
                margin-bottom: 0.5rem;
                border-left: 3px solid {status_color};'>
        <div style='display: flex;
                    justify-content: space-between;
                    align-items: start;
                    margin-bottom: 0.5rem;'>
            <div style='flex: 1;'>
                <div style='color: #f9fafb;
                            font-weight: 600;
                            font-size: 0.875rem;'>
                    Item Title
                </div>
                <div style='color: #3b82f6;
                            font-size: 0.75rem;
                            margin-top: 0.25rem;'>
                    Item Subtitle
                </div>
            </div>
        </div>
        <div style='display: flex;
                    gap: 0.5rem;
                    align-items: center;
                    flex-wrap: wrap;'>
            <!-- Badges here -->
            <div style='color: #64748b;
                        font-size: 0.7rem;
                        margin-left: auto;'>
                Timestamp
            </div>
        </div>
    </div>
""", unsafe_allow_html=True)
```

### 8. Visual Dividers

```python
# Standard divider
st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>",
            unsafe_allow_html=True)

# Gradient divider (inside cards)
st.markdown("<div style='height: 1px; background: linear-gradient(90deg, transparent, #3b82f6, transparent); margin: 1.5rem 0;'></div>",
            unsafe_allow_html=True)

# Simple spacing
st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)
```

### 9. Multiple Badge Display

```python
badges_html = ""
for badge_type, badge_text in [('type', 'Category'), ('status', 'Active')]:
    badge_color = badge_colors.get(badge_type, '#64748b')
    badges_html += f"""
    <div style='background: {badge_color}20;
                border: 1px solid {badge_color};
                color: {badge_color};
                padding: 0.25rem 0.5rem;
                border-radius: 4px;
                font-weight: 600;
                font-size: 0.65rem;
                text-transform: uppercase;
                display: inline-block;
                margin-right: 0.5rem;'>
        {badge_text}
    </div>
    """

st.markdown(f"""
    <div style='display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;'>
        {badges_html}
    </div>
""", unsafe_allow_html=True)
```

### 10. Info Box / Alert

```python
# Success box
st.markdown("""
    <div style='background: #10b981;
                padding: 1rem;
                border-radius: 8px;
                margin-top: 1rem;'>
        <div style='color: #ffffff;
                    font-weight: 700;
                    font-size: 0.75rem;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    margin-bottom: 0.75rem;'>
            Success Title
        </div>
        <div style='color: #ffffff;
                    font-size: 0.875rem;'>
            Message content here
        </div>
    </div>
""", unsafe_allow_html=True)
```

## Layout Patterns

### Two-Column Layout

```python
col1, col2 = st.columns([2, 1])  # 2:1 ratio

with col1:
    # Left column content (wider)
    st.markdown("### Main Content")

with col2:
    # Right column content (narrower)
    st.markdown("### Sidebar")
```

### Four-Column Grid

```python
col1, col2, col3, col4 = st.columns(4)

with col1:
    # Column 1 content
    pass
```

### Expander Pattern

```python
with st.expander("View Details", expanded=False):
    # Content inside expander
    # Note: Cannot nest expanders
    pass
```

## Streamlit Widget Styling

### Text Area (readonly)

```python
st.text_area(
    "Label",
    value=content,
    height=150,
    disabled=True,
    key=f"unique_key_{id}",
    label_visibility="collapsed"  # Hide label
)
```

### Button Styling

```python
# Use container width
if st.button("Button Text", use_container_width=True):
    # Action
    pass

# With help tooltip
if st.button("Button", use_container_width=True, help="Tooltip text"):
    pass
```

## Responsive Patterns

### Conditional Display

```python
# Show content only if data exists
if not data.empty:
    # Show content
    pass
else:
    st.info("No data available")
```

### Safe Data Access

```python
# Handle None/NULL values safely
value = data.get('field') or 'Default Value'

# Safe string slicing
text = data.get('text') or 'N/A'
display_text = text[:30] if len(text) > 30 else text
```

## Progress Indicator Pattern

```python
# Linear progress bar
stages = [
    {'name': 'Stage 1', 'color': '#3b82f6'},
    {'name': 'Stage 2', 'color': '#fbbf24'},
    {'name': 'Stage 3', 'color': '#10b981'}
]

current_index = 1  # Current stage (0-indexed)
progress_width = (current_index / (len(stages) - 1)) * 100

# Build HTML for stages
stages_html = ""
for i, stage in enumerate(stages):
    is_active = i <= current_index
    is_current = i == current_index
    bg_color = stage['color'] if is_active else '#1e40af'

    stages_html += f"""
    <div style='display: flex; flex-direction: column; align-items: center; position: relative;'>
        <div style='width: 1.5rem;
                    height: 1.5rem;
                    border-radius: 50%;
                    background: {bg_color};
                    border: 3px solid {stage['color'] if is_current else bg_color};'></div>
        <div style='color: {"#f9fafb" if is_active else "#64748b"};
                    font-size: 0.7rem;
                    margin-top: 0.5rem;'>
            {stage['name']}
        </div>
    </div>
    """

progress_html = f"""
<div style='background: #1e3a8a;
            padding: 1.25rem;
            border-radius: 8px;
            border: 2px solid #10b981;'>
    <div style='display: flex;
                align-items: center;
                justify-content: space-between;
                position: relative;'>
        <!-- Background line -->
        <div style='position: absolute;
                    top: 0.75rem;
                    left: 2rem;
                    right: 2rem;
                    height: 3px;
                    background: #1e40af;'></div>
        <!-- Progress line -->
        <div style='position: absolute;
                    top: 0.75rem;
                    left: 2rem;
                    width: calc({progress_width}% - 2rem);
                    height: 3px;
                    background: linear-gradient(90deg, #3b82f6, #10b981);'></div>
        {stages_html}
    </div>
</div>
"""

st.markdown(progress_html, unsafe_allow_html=True)
```

## Common Utilities

### HTML Escaping

```python
import html

safe_text = html.escape(user_input)
```

### Date Formatting

```python
from datetime import datetime

formatted_date = date_value.strftime('%b %d, %Y %I:%M %p')
# Output: "Dec 16, 2025 10:30 AM"
```

### Color by Type Helper

```python
def get_type_color(type_value):
    colors = {
        'inquiry': '#3b82f6',
        'booking': '#8b5cf6',
        'confirmed': '#10b981',
        'pending': '#f59e0b',
        'cancelled': '#ef4444',
    }
    return colors.get(type_value, '#64748b')
```

## Best Practices

1. **Always escape user input** when using f-strings in HTML
2. **Use consistent spacing** (margin, padding in rem units)
3. **Keep color scheme consistent** across components
4. **Use semantic color meanings** (green=success, red=error, etc.)
5. **Mobile-friendly**: Use flex and grid layouts
6. **Accessibility**: Maintain good contrast ratios
7. **Performance**: Cache data loading with `@st.cache_data`
8. **Keys**: Always use unique keys for widgets with `key=f"prefix_{id}"`

## Example: Complete Email Display

```python
for email_idx, email in enumerate(emails):
    # Determine status
    if email.get('processed'):
        status_color = '#10b981'
        status_text = 'Processed'
    else:
        status_color = '#fbbf24'
        status_text = 'Unprocessed'

    # Email type color
    email_type = email.get('email_type', 'unknown')
    type_color = get_type_color(email_type)

    # Safe data extraction
    subject = html.escape(str(email.get('subject') or 'No Subject'))
    from_email = html.escape(str(email.get('from_email') or 'N/A'))
    received_at = email.get('received_at_formatted', 'N/A')

    # Display card
    st.markdown(f"""
        <div style='background: #2d3e50;
                    padding: 0.75rem;
                    border-radius: 6px;
                    margin-bottom: 0.5rem;
                    border-left: 3px solid {status_color};'>
            <div style='display: flex;
                        justify-content: space-between;
                        margin-bottom: 0.5rem;'>
                <div style='flex: 1;'>
                    <div style='color: #f9fafb;
                                font-weight: 600;
                                font-size: 0.875rem;'>
                        {subject}
                    </div>
                    <div style='color: #3b82f6;
                                font-size: 0.75rem;
                                margin-top: 0.25rem;'>
                        From: {from_email}
                    </div>
                </div>
            </div>
            <div style='display: flex;
                        gap: 0.5rem;
                        align-items: center;'>
                <div style='background: {type_color}20;
                            border: 1px solid {type_color};
                            color: {type_color};
                            padding: 0.25rem 0.5rem;
                            border-radius: 4px;
                            font-weight: 600;
                            font-size: 0.65rem;
                            text-transform: uppercase;'>
                    {email_type}
                </div>
                <div style='background: {status_color}20;
                            border: 1px solid {status_color};
                            color: {status_color};
                            padding: 0.25rem 0.5rem;
                            border-radius: 4px;
                            font-weight: 600;
                            font-size: 0.65rem;
                            text-transform: uppercase;'>
                    {status_text}
                </div>
                <div style='color: #64748b;
                            font-size: 0.7rem;
                            margin-left: auto;'>
                    {received_at}
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # Show body
    body_text = email.get('body_text') or 'No body text available'
    st.text_area(
        "Email Body",
        value=body_text,
        height=100,
        disabled=True,
        key=f"email_body_{email_idx}",
        label_visibility="collapsed"
    )
```
