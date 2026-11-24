# Antigravity Control Center

A simple, fun Windows companion app for **Google Antigravity IDE** that lives in your system tray.  
Switch between Google accounts in one click, keep an eye on your live AI quotas, track your daily token stats and coding streaks, and peek inside active AI sessions — all in one clean dashboard.

---

## What Can It Do?

If you use **Google Antigravity IDE** every day (especially with more than one Google account), it's annoying to guess how much quota you have left or log out and back in just to switch accounts. **Antigravity Control Center** solves that and gives you fun stats on how you code with AI.

### 1. Accounts & Live Quotas
- **See all your accounts in one place:** View your **5-hour** and **weekly** quota bars for Gemini and Claude models, along with countdown timers for when they reset.
- **1-Click Account Switching:** Switch your active Antigravity account straight from the app or right from the **Windows system tray** icon.
- **Smart Suggestions:** Automatically highlights when your current account is healthy, running low, or which backup account is best to switch to next.
- **Easy Sign-In:** Import the account you're already using in Antigravity with one click, or add extra Google accounts through your browser.
- **Safe Local Storage:** Your saved logins are encrypted using Windows' built-in security (DPAPI) and stay on your own PC.

### 2. Token Analytics & Coding Heatmaps
- **Live Usage Stats:** See your total tokens used, prompt cache hit rate (how much quota you're saving), input vs. output ratio, and live speed (`tokens/sec`).
- **52-Week Coding Heatmap:** A GitHub-style activity grid showing your daily coding volume, active days, and current streak.
- **Day vs. Night Charts:** Find out what hours of the day you code the most, plus which AI models you rely on most.
- **Optimizer Stats:** Tracks token and turn savings if you use `context-mode` or `agy-fast`.
- **Easy Exports:** Filter by Today, 7 Days, Month, Year, or All Time, then export a neat **HTML report**, **CSV**, **JSON**, or back up your history database in one click.

### 3. Session & Fleet Inspector
- **Peek Inside Live Chats:** Watch your active Antigravity conversations (and background subagents) update in real time.
- **Context Window Meter:** See how full a chat's memory is and how many times it has compacted.
- **Step-by-Step Breakdown:** Click any turn in a conversation to see how many tokens that step used.
- **Quick Cleanup:** Clean up leftover session lock files or check the live activity log if anything looks stuck.

### 4. Built to Stay Out of Your Way
- **Tiny Tray Companion:** Runs quietly in your Windows system tray using minimal memory. Closing the window frees the display memory while keeping tracking running in the background.
- **Antigravity Top-Bar Pill (Optional):** Includes helper scripts in `scripts/` that can place a small live quota indicator right inside Antigravity IDE's top bar.

---

## Running the App

### Option A: Using the Windows `.exe` (Standalone Build)
If you build or download the standalone Windows `.exe` version, **you do NOT need to install Python or any Python libraries** — everything the app needs is already packed inside it.

> **Note:** The only optional extra is **Node.js**, and only if you choose to use the `scripts/` add-on for the Antigravity IDE top-bar indicator. Everything in the Control Center app itself works without it.

---

### Option B: Running from Source (Developers)

**What you need:**
- **Windows 10 or Windows 11**
- **Python 3.10+**
- **Node.js** *(optional — only needed if you use the `scripts/` IDE top-bar helper)*

**Steps:**

1. Clone this repo:
   ```powershell
   git clone https://github.com/3bdyna/Antigravity-Control-Center.git
   cd Antigravity-Control-Center
   ```

2. Install the UI package:
   ```powershell
   pip install PyQt5 PyQtWebEngine
   ```

3. Start the app:
   ```powershell
   python main.py
   ```

**Optional launch flags:**
- `python main.py --daemon` — Starts quietly in the system tray without opening the window.
- `python main.py --ui` — Opens the dashboard window.

### Building Your Own `.exe`
Want to package it into a standalone Windows app?
```powershell
pip install pyinstaller
pyinstaller AntigravityControlCenter.spec --noconfirm
```
Your `.exe` will be created in `dist/AntigravityControlCenter/AntigravityControlCenter.exe`.

---

## Your Data Stays Private

Everything is stored locally on your computer under `%USERPROFILE%\.gemini\antigravity-switcher\` (saved encrypted accounts, quota cache, and your local `tokens_history.db` database). Nothing is uploaded to any third-party server.

---

## Search Keywords
`Google Antigravity` · `Antigravity IDE` · `Antigravity Control Center` · `Multi-Account Switcher` · `AI Quota Monitor` · `Token Tracker` · `LLM Usage Analytics` · `Coding Heatmap` · `Session Inspector` · `Windows System Tray` · `Gemini` · `Claude`
