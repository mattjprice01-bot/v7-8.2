from server import app
from shadow_learning import start_background as start_shadow_learning


@app.on_event("startup")
def _start_shadow_learning():
    start_shadow_learning()
