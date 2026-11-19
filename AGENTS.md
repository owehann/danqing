# Danqing Workspace Agent Rules

## Local Server Restart & Port Safety Law (Mandatory)
- **Never run `lsof -ti :8765 | xargs kill -9`** (or any `lsof -ti :<PORT> | xargs kill` without `-sTCP:LISTEN`).
  - Without `-sTCP:LISTEN`, `lsof` returns client processes connected to `127.0.0.1:8765` (such as Antigravity's `NetworkService` helper and Google Chrome), which kills Antigravity's connection to `language_server` (`"Lost connection to language server"`).
- **Always restart Danqing Studio safely** via:
  - `./scripts/start_studio.sh --restart` (built-in listener-only cleanup), or
  - `lsof -tiTCP:8765 -sTCP:LISTEN | xargs kill -9 2>/dev/null || true`
