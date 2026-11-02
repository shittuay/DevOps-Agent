# DevOps Agent for iPhone

A Capacitor app that opens devopsagent.io and adds what only an app can do:
- push notifications when an action is waiting for your confirmation or approval;
- Face ID before a confirmed action runs;
- a Share button on the agent's replies;
- an offline screen.

The website itself is the app's content, so most changes ship by deploying the site; you only
rebuild the app when something in this folder changes.

- Bundle ID: `io.devopsagent.app` (can't be changed once registered with Apple)
- iPhone only (no iPad build), iOS 15 or newer
- Capacitor 8.5.3; plugin versions are pinned exactly in `package.json`

The app has **no buying**. The server hides prices, plans and Billing when it sees the app's
user agent (`DevOpsAgentiOS`, set by `appendUserAgent` in `capacitor.config.json`); see
`services/app_client.py`. Keep it that way, or Apple will require its in-app purchase.

## One-time setup

1. **Apple Developer account:** in Certificates, Identifiers & Profiles › Identifiers, register
   the App ID `io.devopsagent.app` with the **Push Notifications** capability ticked.
2. **Push key for the server:** under Keys, create a key with Apple Push Notifications service
   (APNs) enabled and download the `.p8` file. Then set these four values on the server, in the
   `devops-agent/production` secret or the server's `.env`, and restart:
   - `APNS_KEY`: the text of the `.p8` file;
   - `APNS_KEY_ID`: the key's ID;
   - `APNS_TEAM_ID`: your Team ID;
   - `APNS_BUNDLE_ID`: `io.devopsagent.app`.
3. **App Store Connect:** create a new app with that bundle ID.

## Build and run (on your Mac)

You need Xcode 16 or newer and Node 22.

```bash
cd mobile
npm ci
npx cap sync ios      # copies the config and web files into the Xcode project
npx cap open ios      # opens Xcode
```

In Xcode:
1. Select the **App** target, open **Signing & Capabilities**, and pick your Team.
2. Check that **Push Notifications** is listed. The entitlements file is already in the
   project, but Xcode may ask you to confirm the capability.
3. Plug in your iPhone, pick it as the run target, and press Run.

Push notifications don't work in the Simulator; test them on a real phone. A build run from
Xcode gets a *sandbox* push token, and TestFlight and App Store builds get *production* ones.
The server tries the other one automatically if Apple rejects a token, so both work.

## Release to TestFlight and the App Store

1. Bump **Version** (for example 1.0.1) and **Build** (1, 2, 3...) on the App target's
   General tab.
2. Product › Archive, then Distribute App › App Store Connect › Upload.
3. In App Store Connect, add the build to TestFlight and test it on your phone.
4. For review, provide:
   - **Screenshots:** iPhone 6.9" (1320 x 2868) at minimum.
   - **Privacy policy URL:** a page on devopsagent.io.
   - **App Privacy answers:** account info (email, name), the chats you send, push tokens,
     and the cloud account details you connect. None of it is used for tracking.
   - **A sign-in for the reviewer:** a Free account with **Sandbox mode** on, so they can try
     the agent without a real cloud account. Put its email and password in the review notes.
   - **Review notes:**
     - The app is a free companion to the DevOps Agent web service. It has no purchases and
       no links to buy (guideline 3.1.3(f)).
     - Accounts can be deleted in Settings › Profile › Delete account.

## What's where

- `capacitor.config.json`: app id, name, start URL, the user-agent marker, offline page.
- `www/`: what's bundled in the app. `offline.html` shows when the site can't be reached.
- `ios/App/App/AppDelegate.swift`: forwards the push token to the plugin.
- `ios/App/App/Info.plist`: includes the Face ID message (the app crashes on Face ID without it).
- `ios/App/App/App.entitlements`: the push notification entitlement.
- `../static/js/native_app.js`: the page script that uses the native features. It is part of
  the website, so changes to it ship with a site deploy, not an app update.

## Known risks

- Capacitor's docs say `server.url` (loading the live site) "is not intended for use in
  production", and Apple rejects apps that are only a website (guideline 4.2). The push
  notifications, Face ID, sharing and offline screen are what make this more than a website,
  so mention them in the review notes. If Apple still rejects it under 4.2, the next step is to
  build more of the app natively.
- None of this has been built or run on a real device yet: the project was generated on Linux,
  with no Xcode. Your first Xcode build is the first real test.
