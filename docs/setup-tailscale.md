# Tailscale setup — phone access from any network

The point: stop dealing with LAN-IP changes. Once Tailscale is installed
on your Mac and your phone, both get a stable `100.x.y.z` address that
follows them across any WiFi or cellular network. Private mesh — no public
exposure, no auth surface to harden, free for personal use.

## Mac side (5 min)

1. Install the official Tailscale app:
   - Easiest: download from <https://tailscale.com/download/macos>
     (regular .pkg installer)
   - Or via Mac App Store: search "Tailscale"
   - Or via Homebrew: `brew install --cask tailscale-app`

2. Launch Tailscale (menu-bar icon appears). Click "Sign in" → authenticate
   with whichever provider you prefer (Google / Microsoft / GitHub / email).

3. Once connected, hover the menu-bar icon. You'll see your Mac's Tailscale
   address — something like `100.64.10.42`. **Note it down.**

   You can also get it from the terminal:

   ```bash
   /Applications/Tailscale.app/Contents/MacOS/Tailscale ip -4
   ```

## Phone side (3 min)

1. Install Tailscale from App Store (iOS) or Play Store (Android).
2. Sign in with the same account you used on the Mac.
3. Toggle the VPN on. Wait for "Connected" status.

That's it. Both devices are now in your private "tailnet."

## Use the PWA

Once both ends are connected, the FXTrader dashboard is reachable at:

```
http://<your-Mac-tailnet-IP>:5179
```

For example: `http://100.64.10.42:5179`

Add to home screen on your phone. Works on home WiFi, cellular, café WiFi
— anywhere your phone has internet AND Tailscale toggled on.

## Once connected, tell me your Mac's tailnet IP

I'll add it to the backend's CORS allowlist (cosmetic — shouldn't be
required because the frontend uses same-origin requests, but cleaner
than relying on default-allow). Then we're done.

## Notes

- The Mac must be **awake** for the engine to keep ticking. If the Mac
  sleeps, the trading loop pauses (but no broken state — it resumes when
  the Mac wakes). If you want truly always-on, that's the VPS option.
- Tailscale is encrypted. Your traffic never leaves the tailnet.
- No port forwarding, no public exposure. The kill switch on the PWA is
  reachable only by devices in your tailnet.
