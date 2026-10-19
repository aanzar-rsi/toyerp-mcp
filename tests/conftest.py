import os
import tempfile

# Must run before any `server.db` import so its module-level DB_PATH picks up
# an isolated, throwaway database for the test session.
_tmp_dir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp_dir, "test_erp.db")
