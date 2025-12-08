# Database Migration: Island to TeeMail Demo

## Overview
This migration removes all "Island Golf Club" references from the database and replaces them with "TeeMail Demo" identifiers.

## Tables Affected
1. **bookings** - `club` column
2. **waitlist** - `club` column
3. **dashboard_users** - `customer_id` column
4. **dashboard_users** - `full_name` column (user display names)

## Mapping Changes

| Old Value | New Value |
|-----------|-----------|
| `island` | `teemail` |
| `islandgolfclub` | `teemailclub` |
| `island-golf-club` | `teemail-demo` |
| `island_golf_club` | `teemail_demo` |
| **User full_name with "Island"** | **"TeeMail Demo"** |

## Pre-Migration Checklist

- [ ] **Backup your database** before running the migration
- [ ] Verify you have the correct database connection
- [ ] Test on a development/staging environment first
- [ ] Notify users of potential downtime if necessary

## Running the Migration

### Step 1: Fix User Display Names (Run First)

This fixes the navigation panel showing "The Island Golf Club" as the username:

```bash
psql $DATABASE_URL -f fix_username_display.sql
```

### Step 2: Full Database Migration

After fixing user names, run the full migration:

#### Option 1: Using psql (Recommended)

```bash
# Connect to your database
psql $DATABASE_URL

# Run the migration script
\i migration_island_to_teemail.sql
```

### Option 2: Using SQL Client

1. Connect to your PostgreSQL database
2. Open `migration_island_to_teemail.sql`
3. Execute the entire script
4. Review the output for verification

### Option 3: Direct Command

```bash
psql $DATABASE_URL -f migration_island_to_teemail.sql
```

## Post-Migration Steps

1. **Verify the migration**:
   - Check that no 'island' references remain
   - Verify user logins still work
   - Test booking and waitlist functionality

2. **Update user credentials** (if needed):
   - Users may need to re-login
   - Session data will be cleared on next login

3. **Monitor for errors**:
   - Check application logs
   - Verify data integrity

## Rollback

The migration runs in a transaction. If issues occur during execution:

```sql
ROLLBACK;
```

If you need to rollback after committing, you'll need to:
1. Restore from your database backup
2. OR manually run the reverse migration:

```sql
BEGIN;
UPDATE bookings SET club = 'island' WHERE club = 'teemail';
UPDATE waitlist SET club = 'island' WHERE club = 'teemail';
UPDATE dashboard_users SET customer_id = 'island' WHERE customer_id = 'teemail';
-- Repeat for other variants...
COMMIT;
```

## Verification Queries

After migration, run these queries to verify:

```sql
-- Check bookings
SELECT club, COUNT(*) FROM bookings GROUP BY club;

-- Check waitlist
SELECT club, COUNT(*) FROM waitlist GROUP BY club;

-- Check users
SELECT customer_id, username, full_name FROM dashboard_users;

-- Verify no island references remain
SELECT * FROM bookings WHERE club ILIKE '%island%';
SELECT * FROM waitlist WHERE club ILIKE '%island%';
SELECT * FROM dashboard_users WHERE customer_id ILIKE '%island%';
```

## Support

If you encounter issues:
1. Check the migration output for error messages
2. Verify your database connection
3. Ensure you have proper permissions (UPDATE, SELECT)
4. Review the pre-migration checklist

## Notes

- The code has been updated to use the new identifiers
- Webhook configurations remain unchanged (no hardcoded island references)
- All display names now show "TeeMail Demo"
- Color scheme and branding have been updated accordingly
