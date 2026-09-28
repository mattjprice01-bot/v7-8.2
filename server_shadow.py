import server
import shadow_learning

app = server.app


@app.on_event("startup")
def _start_shadow_learning():
    # Initialise the exact same database/schema used by the live V7.9 server
    # before the observational worker starts. This avoids startup ordering races
    # and guarantees the shadow layer never opens a separate SQLite database.
    c = server.db()
    c.close()
    shadow_learning.DB = server.DB
    shadow_learning.start_background()
