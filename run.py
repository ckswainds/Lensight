import uvicorn
import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    print(f"Starting Lensight AI Local Server on http://localhost:{port}")
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True)
