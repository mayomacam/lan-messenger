
import time

class AuditLogger:
    def __init__(self, db):
        self.db = db

    def log(self, event_type, details, ip_address=None):
        """Log a security event."""
        print(f"[AUDIT] {event_type}: {details} (IP: {ip_address})")
        if self.db:
            try:
                # Use a fresh connection if this one is closed or from another thread
                # Actually Database class handles locking.
                # But "Cannot operate on a closed database" means the connection object itself is closed.
                self.db.add_audit_log(event_type, details, ip_address=ip_address)
            except Exception as e:
                print(f"[ERROR] Failed to write audit log: {e}")

# Global logger instance will be initialized in main app
_logger = None

def init_logger(db):
    global _logger
    _logger = AuditLogger(db)

def get_logger():
    return _logger
