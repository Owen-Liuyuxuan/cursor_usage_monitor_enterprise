# Security model

- Cursor's SQLite database is opened with `mode=ro` and is never modified.
- Only `cursorAuth/accessToken`, membership type, and cached team display name
  are read. `cursorAuth/refreshToken` is never queried.
- When Cursor stores a `cursor-safe-storage:v1` envelope, the service reads the
  Cursor Chromium OSCrypt password from GNOME Keyring (libsecret application
  `Cursor`) and decrypts the token in memory. The keyring password and
  plaintext token are never written, logged, or placed on D-Bus.
- The access token exists only inside the Python service process and HTTPS
  request headers. It is absent from D-Bus, settings, notifications, and logs.
- D-Bus responses contain numeric usage, cycle dates, and account/team labels.
- HTTP errors are reduced to safe status messages; response bodies are not
  forwarded to the desktop.

The personal dashboard endpoints are undocumented. Review changes to
`client.py` carefully and never add debug logging for headers, cookies, tokens,
or raw Cursor database rows.
