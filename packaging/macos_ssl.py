"""Give bundled urllib HTTPS requests a portable certificate bundle."""
import os
from pathlib import Path
import sys

os.environ.setdefault('SSL_CERT_FILE', str(Path(sys._MEIPASS) / 'certificates' / 'cert.pem'))
