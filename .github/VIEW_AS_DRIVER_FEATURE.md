# View As Driver Feature - Admin Troubleshooting Tool

## Overview
The "View As Driver" feature allows administrators to impersonate driver accounts for troubleshooting purposes. This lets admins see exactly what a driver sees without needing their password.

## Key Features

### 1. **Session-Based Impersonation**
- Admin can switch to a driver's view without logging out
- Original admin session is preserved in session storage
- Admin can return to their account with one click

### 2. **Visual Indicators**
- **Red banner** appears at top of every page when impersonating
- Banner shows:
  - Current driver username and name
  - Original admin username
  - "Exit View As" button

### 3. **Security Restrictions**
- Only staff members can use this feature (`@staff_member_required`)
- Cannot impersonate other staff or admin users
- All impersonation actions are logged

### 4. **Audit Trail**
- System creates notification when impersonation starts
- Tracks:
  - Who impersonated whom
  - When it started
  - How long the session lasted

## How to Use

### Starting Impersonation
1. Go to Admin → User Search
2. Find the driver you want to troubleshoot
3. Click **"🔍 View As Driver"** button
4. Confirm the action
5. You'll be redirected to the driver's profile page

### While Impersonating
- You see exactly what the driver sees
- Red warning banner at top shows you're in admin mode
- You can navigate the entire site as the driver
- All permissions are the driver's (not yours)

### Ending Impersonation
1. Click **"Exit View As → Return to [your username]"** in the red banner
2. You'll be logged back in as admin
3. Redirected to Admin User Search page
4. Success message shows duration of impersonation

## Technical Implementation

### Files Modified

#### 1. `accounts/views.py`
- `view_as_driver(request, user_id)` - Starts impersonation
- `stop_impersonation(request)` - Ends impersonation and restores admin session

#### 2. `accounts/urls.py`
```python
path("admin/users/<int:user_id>/view-as/", views.view_as_driver, name="view_as_driver"),
path("admin/stop-impersonation/", views.stop_impersonation, name="stop_impersonation"),
```

#### 3. `accounts/context_processors.py`
- `impersonation_status(request)` - Makes impersonation state available to all templates

#### 4. `truckincentive/settings.py`
- Added `"accounts.context_processors.impersonation_status"` to context processors

#### 5. `templates/base.html`
- Added red warning banner that appears during impersonation
- Shows current user and exit button

#### 6. `templates/accounts/admin_user_search.html`
- Added "View As Driver" button to driver actions

## Session Data Structure

During impersonation, these session keys are set:
```python
{
    'impersonate_id': 123,  # Original admin user ID
    'impersonate_username': 'admin_user',  # Original admin username
    'impersonate_started': '2025-10-28T15:30:00'  # ISO format timestamp
}
```

## Use Cases

### 1. **Troubleshoot Display Issues**
- Driver reports points not showing correctly
- Admin views as driver to see their exact view
- Can verify points, orders, notifications

### 2. **Test Permissions**
- Verify what features driver can/cannot access
- Check sponsor-specific visibility
- Confirm catalog filtering works correctly

### 3. **Reproduce Bugs**
- Driver reports "button doesn't work"
- Admin views as driver to reproduce exact scenario
- Can test with driver's actual data

### 4. **Verify Fixes**
- After fixing a driver-specific issue
- Admin impersonates to confirm fix works
- No need to ask driver to test

### 5. **Training & Demonstrations**
- Show other admins how driver view looks
- Document workflows from driver perspective
- Create screenshots for help documentation

## Limitations

### What You CAN Do
✅ View all pages the driver can access
✅ See their profile, points, orders
✅ Navigate catalog as they see it
✅ View their notifications and messages
✅ Test UI interactions

### What You CANNOT Do
❌ Impersonate other admins or staff
❌ Change the driver's password while impersonating
❌ Delete the driver's account
❌ Bypass normal permission checks

## Best Practices

1. **Always inform drivers** when possible before impersonating
2. **Document why** you're impersonating in support tickets
3. **Keep sessions short** - only as long as needed to troubleshoot
4. **Exit immediately** after resolving the issue
5. **Review audit logs** regularly to track impersonation usage

## Troubleshooting

### "Cannot impersonate staff or admin users"
- This is intentional - only driver accounts can be impersonated
- Use regular admin access for staff account issues

### Banner not showing
- Clear browser cache
- Check context processor is registered in settings
- Verify session data exists: `request.session.get('impersonate_id')`

### Can't exit impersonation
- Manually clear session: Delete `impersonate_*` keys
- Or log out and log back in as admin

### Session expired during impersonation
- Original admin session data lost
- Must log in again normally
- Consider increasing `SESSION_COOKIE_AGE` in settings

## Future Enhancements

Potential improvements:
- [ ] Add impersonation history page (who impersonated whom and when)
- [ ] Restrict certain actions during impersonation (e.g., can't purchase items)
- [ ] Add "read-only mode" option
- [ ] Email notification to driver when impersonation occurs
- [ ] Time limit for impersonation sessions
- [ ] Require justification text before impersonating

## Security Considerations

- Only staff can access this feature
- Cannot impersonate privileged accounts
- All actions are logged with timestamps
- Session data includes original admin identity
- Original admin session is restored (not a new login)
- Impersonation state is visible at all times (red banner)
