"""
호환 진입점 — python server.py

새 구조:
  python -m bridge.main   # :3001
  python -m portal.main   # :3000
"""

from portal.main import create_app, main

app = create_app()

if __name__ == "__main__":
    main()
