import sys
sys.path.insert(0, ".")
import presets
from engines import engine_status

for p in presets.list_presets():
    st = engine_status(p)
    print(f"{p['id']:32s} | engine: {p.get('engine'):15s} | avail: {st['available']} (reason: {st.get('reason')})")
