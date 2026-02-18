# Navigation Guide - All Pages Connected

## 🎯 How Everything is Connected

Your DevOps Agent now has **unified navigation** across all pages! Here's how to navigate:

---

## 📍 Main Navigation Menu

### From the Chat Page (Main Interface)

At the top-right, click the **☰ Menu** button to access:

```
☰ Menu
├── 🔧 View Tools       → Shows available DevOps tools
├── 📊 Statistics       → Shows usage statistics
├── ─────────────
├── 💳 Billing & Credits → /billing
├── 👤 Profile          → /profile
├── ⚡ Templates        → /templates
├── ⚙️ Settings         → /settings
├── ─────────────
├── ℹ️ About            → About the agent
└── 🚪 Logout           → Log out
```

### Credits Badge (Always Visible)

In the top-right corner, you'll see:

```
💰 20 credits
```

**Features:**
- **Click** to go to /billing
- **Color-coded** status:
  - 🟢 Green (>5 credits) → Normal
  - 🟡 Yellow (≤5 credits) → Low warning
  - 🔴 Red (0 credits) → Out of credits
- **Auto-updates** after each message
- **Refreshes** every 30 seconds

---

## 🗺️ Page-by-Page Navigation

### 1. Chat Page (`/chat`)

**Location:** Main interface
**Navigation:**
- **Header:** Credits badge + Menu dropdown
- **Sidebar:** Conversation history
- **Bottom:** Message input

**Links to:**
- `/billing` → Click credits badge or Menu → Billing & Credits
- `/profile` → Menu → Profile
- `/settings` → Menu → Settings
- `/templates` → Menu → Templates
- `/logout` → Menu → Logout

---

### 2. Billing Page (`/billing`)

**Location:** `http://localhost:5000/billing`
**Navigation:**
- **Top:** "← Back to Chat" link

**What's Here:**
- Current credit balance (big number)
- Progress bar showing usage
- Current tier badge
- All 4 subscription tiers
- Credit pack options
- Upgrade/Purchase buttons

**Links to:**
- `/chat` → Back to Chat link (top)
- Tier upgrades → API calls (stay on page)
- Credit purchases → API calls (stay on page)

---

### 3. Profile Page (`/profile`)

**Location:** `http://localhost:5000/profile`
**Navigation:**
- **Bottom:** "Back to Chat" button

**What's Here:**
- Edit full name
- Change bio
- Avatar color picker
- Theme selection (light/dark)
- Account info

**Links to:**
- `/chat` → Back to Chat button

---

### 4. Settings Page (`/settings`)

**Location:** `http://localhost:5000/settings`
**Navigation:**
- **Top:** "← Back to Chat" link

**What's Here:**
- AWS credentials configuration
- API key settings
- Cloud provider settings

**Links to:**
- `/` or `/chat` → Back to Chat link

---

### 5. Templates Page (`/templates`)

**Location:** `http://localhost:5000/templates`
**Navigation:**
- Similar to Settings

**What's Here:**
- Command templates
- Quick access commands
- Custom shortcuts

**Links to:**
- `/chat` → Back link

---

## 🎨 Visual Flow

```
┌─────────────────────────────────────────────┐
│  Chat Page (/chat) - MAIN HUB               │
│  ┌────────────────────────────────────┐    │
│  │ Header: [💰 Credits] [Menu ☰]     │    │
│  └────────────────────────────────────┘    │
│                                              │
│  ┌──────────┐  ┌─────────────────────┐    │
│  │Sidebar   │  │  Chat Messages       │    │
│  │History   │  │                      │    │
│  └──────────┘  └─────────────────────┘    │
│                                              │
│  Menu Dropdown:                              │
│  ┌────────────────────────────┐            │
│  │ 💳 Billing & Credits ───────┼──┐        │
│  │ 👤 Profile ─────────────────┼─┐│        │
│  │ ⚡ Templates ───────────────┼┐││        │
│  │ ⚙️ Settings ────────────────┼│││        │
│  │ 🚪 Logout                   │││││        │
│  └────────────────────────────┘││││        │
└──────────────────────────────────┼┼┼┼──────┘
                                   │││││
         ┌─────────────────────────┘│││
         │                          │││
         ▼                          │││
┌────────────────────┐              │││
│  Billing Page      │◄─────────────┘││
│  (/billing)        │               ││
│                    │               ││
│  ┌──────────────┐ │               ││
│  │ ← Back       │ │               ││
│  └──────────────┘ │               ││
│                    │               ││
│  💰 Credits: 20    │               ││
│  ━━━━━━━━━━━━━    │               ││
│                    │               ││
│  [Tier Cards]      │               ││
│  [Credit Packs]    │               ││
└────────────────────┘               ││
                                     ││
         ┌───────────────────────────┘│
         │                            │
         ▼                            │
┌────────────────────┐                │
│  Profile Page      │◄───────────────┘
│  (/profile)        │
│                    │
│  [Edit Profile]    │
│  [Back to Chat]    │
└────────────────────┘

         │
         ▼
    [Settings]
    [Templates]
    [Logout]
```

---

## 🔄 Navigation Patterns

### Pattern 1: Quick Access from Chat

```
Chat → Click Credits Badge → Billing → Back to Chat
```

### Pattern 2: Menu Navigation

```
Chat → Menu → Profile → Edit → Back to Chat
Chat → Menu → Settings → Configure → Back to Chat
Chat → Menu → Billing → Upgrade → Back to Chat
```

### Pattern 3: Credits Workflow

```
Chat → Send Message → Credits Deduct → Badge Updates
     → Out of Credits → Prompt → Billing → Purchase → Chat
```

---

## 💡 Pro Tips

### 1. **Always Visible Credits**
Your credit count is **always visible** in the header. No need to navigate away to check!

### 2. **One-Click Access**
Click the credits badge **anytime** to jump to billing page.

### 3. **Menu Shortcuts**
Use the Menu (☰) to quickly jump between:
- Billing (💳)
- Profile (👤)
- Settings (⚙️)
- Templates (⚡)

### 4. **Back Links**
Every page has a **← Back to Chat** link to return to the main interface.

### 5. **Auto-Refresh**
Credits automatically refresh every 30 seconds, so you always see current balance.

---

## 🎯 Common User Journeys

### Journey 1: Check Credits & Upgrade

```
1. Login → /chat
2. See credits badge (top-right)
3. Click credits badge → /billing
4. Review tier options
5. Click "Upgrade" on desired tier
6. See confirmation
7. Click "← Back to Chat"
8. Continue chatting with more credits
```

### Journey 2: Use Agent Until Out of Credits

```
1. Chat → Send message (19 credits left)
2. Chat → Send message (18 credits left)
   ...
3. Chat → Send message (1 credit left)
4. Badge turns RED
5. Chat → Send message (0 credits)
6. See "Out of Credits" message
7. Prompt: "View billing options?"
8. Click "Yes" → /billing
9. Purchase credit pack or upgrade
10. Return to chat
```

### Journey 3: Manage Profile

```
1. /chat → Menu ☰ → Profile
2. /profile → Edit name, bio, theme
3. Save changes
4. Back to Chat
```

---

## 📱 Keyboard Navigation

While not implemented yet, here are suggested shortcuts:

- `Ctrl + B` → Billing
- `Ctrl + P` → Profile
- `Ctrl + S` → Settings
- `Ctrl + /` → Open Menu
- `Escape` → Close Menu/Modal

---

## 🔗 All Routes Summary

| Page | URL | Access From |
|------|-----|-------------|
| **Chat** | `/chat` | Login, all back links |
| **Billing** | `/billing` | Menu, Credits badge |
| **Profile** | `/profile` | Menu |
| **Settings** | `/settings` | Menu |
| **Templates** | `/templates` | Menu |
| **Login** | `/login` | Logout, unauthenticated |
| **Signup** | `/signup` | Login page link |
| **Logout** | `/logout` | Menu |

---

## ✅ Testing Navigation

### Test 1: Full Circle
1. Start at `/chat`
2. Click Menu → Billing
3. At `/billing`, click "← Back to Chat"
4. Should return to `/chat`

### Test 2: Credits Badge
1. At `/chat`, note credits count
2. Send a message
3. Badge should update (decrease by 1)
4. Click badge
5. Should go to `/billing`

### Test 3: Menu Items
1. Click Menu ☰
2. Click each item:
   - ✅ Billing → Goes to /billing
   - ✅ Profile → Goes to /profile
   - ✅ Templates → Goes to /templates
   - ✅ Settings → Goes to /settings
   - ✅ Logout → Logs out

### Test 4: Out of Credits Flow
1. Use up all credits (send 20 messages)
2. Try to send 21st message
3. Should see error + prompt
4. Click "Yes"
5. Should go to /billing
6. Purchase credits
7. Return to chat
8. Can send messages again

---

## 🎉 Summary

**Everything is now connected!**

- ✅ Credits badge in header (always visible)
- ✅ Menu with all navigation links
- ✅ Back links on every page
- ✅ Auto-updating credits
- ✅ Out-of-credits prompts
- ✅ One-click access to billing
- ✅ Seamless navigation flow

**Navigation is intuitive and user-friendly!**

Your users can:
- Check credits without leaving chat
- Access all features from one menu
- Return to chat from anywhere
- Get prompted when action needed
- Navigate with clear visual cues

---

Enjoy your fully-connected DevOps Agent! 🚀
